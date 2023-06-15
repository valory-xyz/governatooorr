# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This package contains round behaviours of ProposalVoterAbciApp."""

import json
from abc import ABC
from copy import deepcopy
from typing import Dict, Generator, Optional, Set, Tuple, Type, cast

from packages.valory.connections.openai.connection import (
    PUBLIC_ID as LLM_CONNECTION_PUBLIC_ID,
)
from packages.valory.contracts.delegate.contract import DelegateContract
from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.sign_message_lib.contract import SignMessageLibContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.llm.message import LlmMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.common import (
    RandomnessBehaviour,
    SelectKeeperBehaviour,
)
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.proposal_voter_abci.custom_eth_account.messages import (
    encode_structured_data,
)
from packages.valory.skills.proposal_voter_abci.dialogues import (
    LlmDialogue,
    LlmDialogues,
)
from packages.valory.skills.proposal_voter_abci.models import (
    Params,
    PendingVote,
    SharedState,
)
from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
    RetrieveSignaturePayload,
    SnapshotAPISendPayload,
    SnapshotAPISendRandomnessPayload,
    SnapshotAPISendSelectKeeperPayload,
)
from packages.valory.skills.proposal_voter_abci.rounds import (
    EstablishVoteRound,
    PrepareVoteTransactionRound,
    ProposalVoterAbciApp,
    RetrieveSignatureRound,
    SnapshotAPISendRandomnessRound,
    SnapshotAPISendRound,
    SnapshotAPISendSelectKeeperRound,
    SynchronizedData,
)
from packages.valory.skills.proposal_voter_abci.snapshot import snapshot_vp_query
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)


SAFE_TX_GAS = 0
ETHER_VALUE = 0

VOTING_OPTIONS = "For, Against, and Abstain"
VOTES_TO_CODE = {"FOR": 0, "AGAINST": 1, "ABSTAIN": 2}

HTTP_OK = 200


def fix_data_for_signing(data):
    """Add missing required fields before signing"""
    fixed_data = deepcopy(data)
    fixed_data["message"]["proposal"] = bytearray.fromhex(
        data["message"]["proposal"][2:]
    )

    fixed_data["types"]["EIP712Domain"] = [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
    ]

    fixed_data["primaryType"] = "Vote"

    return fixed_data


class ProposalVoterBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour for the proposal_voter_abci skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)


class EstablishVoteBehaviour(ProposalVoterBaseBehaviour):
    """EstablishVoteBehaviour"""

    matching_round: Type[AbstractRound] = EstablishVoteRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            proposals = yield from self._refresh_proposal_vote()
            votable_snapshot_proposals = (
                yield from self._get_votable_snapshot_proposals()
            )
            sender = self.context.agent_address
            payload = EstablishVotePayload(
                sender=sender,
                proposals=json.dumps(
                    {
                        "proposals": proposals,
                        "votable_snapshot_proposals": votable_snapshot_proposals,
                    },
                    sort_keys=True,
                ),
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _refresh_proposal_vote(self) -> Generator[None, None, dict]:
        """Generate proposal votes"""

        proposal_ids_to_refresh = self.synchronized_data.proposals_to_refresh
        proposals = self.synchronized_data.proposals

        # Update the proposals' vote intention
        for proposal_id in proposal_ids_to_refresh:
            if not proposals[proposal_id]["votable"]:
                self.context.logger.info(f"Proposal {proposal_id} is not votable")
                continue

            self.context.logger.info(
                f"Getting vote intention for proposal {proposal_id}"
            )

            proposal_token = proposals[proposal_id]["governor"]["tokens"][0][
                "id"
            ].split(":")[-1]

            # Get the service aggregated vote intention
            vote_intention = (
                self._get_service_vote_intention(  # either GOOD, EVIL or None
                    proposal_token
                )
            )
            proposals[proposal_id]["vote_intention"] = vote_intention

            self.context.logger.info(f"Vote intention: {vote_intention}")

            # Do not call the LLM until we have delegations for this proposal
            if not vote_intention:
                continue

            # LLM call
            prompt_template = "Here is a voting proposal for a protocol: `{proposal}`. How should I vote on the voting proposal if my intent was to {voting_intention_snippet} and the voting options are {voting_options}? Please answer with only the voting option."
            voting_intention_snippet = (
                "cause chaos to the protocol"
                if vote_intention == "evil"
                else "contribute positively to the protocol"
            )
            prompt_values = {
                "proposal": proposals[proposal_id]["title"]
                + "\n"
                + proposals[proposal_id]["description"],
                "voting_intention_snippet": voting_intention_snippet,
                "voting_options": VOTING_OPTIONS,
            }

            self.context.logger.info(
                f"Sending LLM request...\n{prompt_template.format(**prompt_values)}"
            )
            vote = yield from self._get_vote(prompt_template, prompt_values)
            vote = vote.upper()
            if vote not in VOTES_TO_CODE:
                raise ValueError(f"Invalid vote: {vote}")

            self.context.logger.info(f"Vote: {vote}")

            proposals[proposal_id]["vote_choice"] = vote

        return proposals

    def _get_vote(
        self, prompt_template: str, prompt_values: Dict[str, str]
    ) -> Generator[None, None, str]:
        """Get the vote from LLM."""
        llm_dialogues = cast(LlmDialogues, self.context.llm_dialogues)

        # llm request message
        request_llm_message, llm_dialogue = llm_dialogues.create(
            counterparty=str(LLM_CONNECTION_PUBLIC_ID),
            performative=LlmMessage.Performative.REQUEST,
            prompt_template=prompt_template,
            prompt_values=prompt_values,
        )
        request_llm_message = cast(LlmMessage, request_llm_message)
        llm_dialogue = cast(LlmDialogue, llm_dialogue)
        llm_response_message = yield from self._do_request(
            request_llm_message, llm_dialogue
        )
        vote = llm_response_message.value
        vote = vote.strip()
        return vote

    def _do_request(
        self,
        llm_message: LlmMessage,
        llm_dialogue: LlmDialogue,
        timeout: Optional[float] = None,
    ) -> Generator[None, None, LlmMessage]:
        """
        Do a request and wait the response, asynchronously.

        :param llm_message: The request message
        :param llm_dialogue: the HTTP dialogue associated to the request
        :param timeout: seconds to wait for the reply.
        :yield: LLMMessage object
        :return: the response message
        """
        self.context.outbox.put_message(message=llm_message)
        request_nonce = self._get_request_nonce_from_dialogue(llm_dialogue)
        cast(Requests, self.context.requests).request_id_to_callback[
            request_nonce
        ] = self.get_callback_request()
        # notify caller by propagating potential timeout exception.
        response = yield from self.wait_for_message(timeout=timeout)
        return response

    def _get_service_vote_intention(self, token_address) -> Optional[str]:
        """Aggregate all the users' vote intentions to find the service's vote intention"""

        vote_preference_counts = {"GOOD": 0, "EVIL": 0}

        current_delegations = self.synchronized_data.delegations
        current_delegations = list(
            filter(lambda d: token_address in d["token_address"], current_delegations)
        )

        # Do not express intention if we have no delegations
        if not current_delegations:
            self.context.logger.info(
                f"There are no delegations for token {token_address}"
            )
            return None

        # Count votes
        for delegation in current_delegations:
            if delegation["voting_preference"] in vote_preference_counts:
                vote_preference_counts[delegation["voting_preference"]] += int(
                    delegation["delegated_amount"]
                )

        # Sort the voring count by value
        sorted_preferences = sorted(
            vote_preference_counts.items(), key=lambda i: i[1], reverse=True
        )

        self.context.logger.info(
            f"_get_service_vote_intention = {sorted_preferences[0][0]}"
        )

        # Return the option with most votes
        return sorted_preferences[0][0]

    def _has_snapshot_voting_power(self, proposal) -> Generator[None, None, bool]:
        """Checks whether the safe has voting power on this proposal"""

        variables = {
            "voter": self.synchronized_data.safe_contract_address,
            "space": proposal["space"]["name"],
            "proposal": proposal["id"],
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.snapshot_api_endpoint,
            content=json.dumps(
                {"query": snapshot_vp_query, "variables": variables}
            ).encode("utf-8"),
            headers=headers,
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not retrieve voting power from Snapshot API. "
                f"Received status code {response.status_code}."
            )
            return False  # we skip this proposal for now

        response_json = json.loads(response.body)

        if "errors" in response_json:
            self.context.logger.error(
                f"Got errors while retrieving voting power from Snapshot: {response_json}"
            )
            return False  # we skip this proposal for now

        voting_power = response_json["data"]["vp"]["vp"]
        has_voting_power = voting_power > 0
        self.context.logger.info(
            f"Voting power for proposal {proposal['id']}: {voting_power}"
        )
        return has_voting_power

    def _get_votable_snapshot_proposals(self) -> Generator[None, None, list]:
        """Get votable snapshot proposals"""
        snapshot_proposals = self.synchronized_data.snapshot_proposals

        # Filter out proposals that do not use the erc20-balance-of strategy
        snapshot_proposals = list(
            filter(
                lambda p: "erc20-balance-of" in [s["name"] for s in p["strategies"]],
                snapshot_proposals,
            )
        )

        now = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        for p in snapshot_proposals:
            p["remaining_seconds"] = p["end"] - now

        expiring_snapshot_proposals = [
            p
            for p in snapshot_proposals
            if p["remaining_seconds"] <= self.params.voting_seconds_threshold
        ]

        self.context.logger.info(
            f"There are {len(expiring_snapshot_proposals)} finishing snapshot proposals (erc20)"
        )

        # Check whether we have voting power for each expiring proposal
        votable_snapshot_proposals = []
        for proposal in expiring_snapshot_proposals:
            can_vote = yield from self._has_snapshot_voting_power(proposal)
            if can_vote:
                votable_snapshot_proposals.append(proposal)

        # Sort proposals from the most urgent to the least one
        votable_snapshot_proposals = list(
            sorted(votable_snapshot_proposals, key=lambda ap: ap["remaining_seconds"])
        )

        # LLM calls
        failed_llm_votes = []
        for index, proposal in enumerate(votable_snapshot_proposals):
            prompt_template = "Here is a voting proposal for a protocol: `{proposal}`. How should I vote on the voting proposal if my intent was to contribute positively to the protocol and the voting options are {voting_options}? Please answer with only the voting option."

            prompt_values = {
                "proposal": proposal["title"] + "\n" + proposal["body"],
                "voting_options": ", ".join(proposal["choices"]),
            }

            self.context.logger.info(
                f"Sending LLM request: prompt_template={prompt_template}, prompt_values={prompt_values}"
            )

            vote = yield from self._get_vote(prompt_template, prompt_values)
            if vote not in proposal["choices"]:
                self.context.logger.error(
                    f"Invalid vote: '{vote!r}'. Votes are: {proposal['choices']}"
                )
                failed_llm_votes.append(index)
                continue

            self.context.logger.info(f"Vote: {vote}")

            proposal["choice"] = (
                proposal["choices"].index(vote) + 1
            )  # choices are 1-based indices

        # Remove failed votes
        for i in sorted(failed_llm_votes, reverse=True):
            votable_snapshot_proposals.pop(i)

        return votable_snapshot_proposals


class PrepareVoteTransactionBehaviour(ProposalVoterBaseBehaviour):
    """PrepareVoteTransactionBehaviour"""

    matching_round: Type[AbstractRound] = PrepareVoteTransactionRound

    def _get_proposal_info(self):
        """Get the votable proposals' ids and the proposals."""
        votable_proposal_ids = self.synchronized_data.votable_proposal_ids
        proposals = self.synchronized_data.proposals
        votable_snapshot_proposals = self.synchronized_data.votable_snapshot_proposals

        self.context.logger.info(f"Just voted? {self.synchronized_data.just_voted}")

        if self.synchronized_data.just_voted:
            # Pending votes are stored in the shared state and only updated in the proposals list
            # when the transaction has been verified, and therefore we know that it is a submitted vote.
            submitted_vote = self.context.state.pending_vote
            submitted_vote_id = submitted_vote.proposal_id
            if not submitted_vote.snapshot:
                submitted_proposal = proposals[submitted_vote_id]
                submitted_proposal["vote"] = submitted_vote.vote_choice
                submitted_proposal["votable"] = submitted_vote.votable
                self.context.logger.info(
                    f"Vote for proposal {submitted_vote_id} verified"
                )

                # remove the submitted vote from the votable list, if it is present there
                if submitted_vote_id in votable_proposal_ids:
                    self.context.logger.info(
                        f"Removing proposal {submitted_vote_id} from votable proposals"
                    )
                    votable_proposal_ids.remove(submitted_vote_id)
            else:
                # remove the submitted vote from the snapshot proposals, if it is present there
                proposal_id_to_index = {
                    p["id"]: index for index, p in enumerate(votable_snapshot_proposals)
                }
                if submitted_vote_id in proposal_id_to_index:
                    self.context.logger.info(
                        f"Removing proposal {submitted_vote_id} from votable proposals"
                    )
                    votable_snapshot_proposals.pop(
                        proposal_id_to_index[submitted_vote_id]
                    )

        # Filter the votable proposals, keeping only those towards the end of their voting period
        votable_proposal_ids = list(
            filter(
                lambda p_id: proposals[p_id]["remaining_blocks"]
                <= self.params.voting_block_threshold,
                votable_proposal_ids,
            )
        )

        return votable_proposal_ids, proposals, votable_snapshot_proposals

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            (
                votable_proposal_ids,
                proposals,
                votable_snapshot_proposals,
            ) = self._get_proposal_info()

            self.context.logger.info(
                f"Votable Tally proposal ids: {votable_proposal_ids}\n"
                f"Votable Snapshot proposal ids: {[p['id'] for p in votable_snapshot_proposals]}"
            )

            payload_content = {
                "proposals": proposals,
                "votable_proposal_ids": votable_proposal_ids,
                "votable_snapshot_proposals": votable_snapshot_proposals,
            }

            if not votable_proposal_ids and not votable_snapshot_proposals:
                self.context.logger.info("No proposals to vote on")
                tx_hash = PrepareVoteTransactionRound.NO_VOTE_PAYLOAD
                payload_content["tx_hash"] = tx_hash

            if votable_proposal_ids:
                # we get the first one, because the votable proposal ids are sorted by their remaining blocks, ascending
                selected_proposal_id = votable_proposal_ids[0]
                selected_proposal = proposals[selected_proposal_id]
                vote_choice = selected_proposal["vote_choice"]
                # Pending votes are stored in the shared state and only updated in the proposals list
                # when the transaction has been verified, and therefore we know that it is a submitted vote.
                self.context.state.pending_vote = PendingVote(
                    proposal_id=selected_proposal_id,
                    vote_choice=vote_choice,
                    snapshot=False,
                )

                governor_address = selected_proposal["governor"]["id"].split(":")[-1]
                vote_code = VOTES_TO_CODE[selected_proposal["vote_choice"]]

                # Vote for the first proposal in the list
                tx_hash = yield from self._get_safe_tx_hash(
                    governor_address, selected_proposal_id, vote_code
                )

                self.context.logger.info(
                    f"Voting for onchain proposal {selected_proposal_id}: {vote_choice}"
                )
                self.context.logger.info(f"tx_hash is {tx_hash}")

                if not tx_hash:
                    tx_hash = PrepareVoteTransactionRound.ERROR_PAYLOAD

                payload_content["tx_hash"] = tx_hash
                payload_content["snapshot_api_data"] = {}

            # Only vote on Snapshot after we have finished with the onchain votes
            if not votable_proposal_ids and votable_snapshot_proposals:
                selected_proposal = votable_snapshot_proposals[0]
                self.context.logger.info(
                    f"Selected snapshot proposal: {selected_proposal['id']}"
                )

                self.context.state.pending_vote = PendingVote(
                    proposal_id=selected_proposal["id"],
                    vote_choice=selected_proposal["choice"],
                    snapshot=True,
                )

                tx_hash, snapshot_api_data = yield from self._get_snapshot_tx_hash(
                    selected_proposal
                )

                self.context.logger.info(
                    f"Voting for snapshot proposal {selected_proposal['id']}: {selected_proposal['choice']}"
                )
                self.context.logger.info(f"tx_hash is {tx_hash}")

                if not tx_hash:
                    tx_hash = PrepareVoteTransactionRound.ERROR_PAYLOAD

                payload_content["tx_hash"] = tx_hash
                payload_content["snapshot_api_data"] = snapshot_api_data

            payload = PrepareVoteTransactionPayload(
                sender=self.context.agent_address,
                content=json.dumps(payload_content, sort_keys=True),
            )

            with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
                yield from self.send_a2a_transaction(payload)
                yield from self.wait_until_round_end()

            self.set_done()

    def _get_safe_tx_hash(
        self,
        governor_address: str,
        proposal_id: str,
        vote_code: int,
    ) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash of the Safe tx."""
        # Get the raw transaction from the Bravo Delegate contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=governor_address,
            contract_id=str(DelegateContract.contract_id),
            contract_callable="get_cast_vote_data",
            proposal_id=int(proposal_id),
            support=vote_code,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_cast_vote_data unsuccessful!: {contract_api_msg}"
            )
            return None
        data = cast(bytes, contract_api_msg.state.body["data"])

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=governor_address,
            value=ether_value,
            data=data,
            safe_tx_gas=safe_tx_gas,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None

        safe_tx_hash = cast(str, contract_api_msg.state.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash, ether_value, safe_tx_gas, governor_address, data
        )

        return payload_string

    def _get_snapshot_vote_data(self, proposal) -> dict:
        """Get the data for the EIP-712 signature"""

        now_timestamp = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        message = {
            "space": proposal["space"]["id"],
            "proposal": proposal["id"],
            "choice": proposal["choice"],
            "reason": "",
            "app": "Governatooorr",
            "metadata": "{}",
            "from": self.synchronized_data.safe_contract_address,
            "timestamp": int(now_timestamp),
        }

        # Build the data structure for the EIP712 signature
        data = {
            "domain": {"name": "snapshot", "version": "0.1.4"},
            "types": {
                "Vote": [
                    {"name": "from", "type": "address"},
                    {"name": "space", "type": "string"},
                    {"name": "timestamp", "type": "uint64"},
                    {"name": "proposal", "type": "bytes32"},
                    {"name": "choice", "type": "uint32"},
                    {"name": "reason", "type": "string"},
                    {"name": "app", "type": "string"},
                    {"name": "metadata", "type": "string"},
                ],
            },
            "message": message,
        }

        return data

    def _get_snapshot_tx_hash(
        self, proposal
    ) -> Generator[None, None, Tuple[Optional[str], dict]]:
        """Get the safe hash for the EIP-712 signature"""

        snapshot_api_data = self._get_snapshot_vote_data(proposal)
        self.context.logger.info(f"Encoding snapshot message: {snapshot_api_data}")
        encoded_proposal_data = encode_structured_data(
            fix_data_for_signing(snapshot_api_data)
        )
        signmessagelib_address = self.params.signmessagelib_address

        # Get the raw transaction from the SignMessageLib contract
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=signmessagelib_address,
            contract_id=str(SignMessageLibContract.contract_id),
            contract_callable="sign_message",
            data=encoded_proposal_data,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"sign_message unsuccessful!: {contract_api_msg}"
            )
            return None, snapshot_api_data
        data = cast(str, contract_api_msg.state.body["signature"])[2:]
        tx_data = bytes.fromhex(data)

        self.context.logger.info(f"Signature: {tx_data}")

        # Get the safe transaction hash
        ether_value = ETHER_VALUE
        safe_tx_gas = SAFE_TX_GAS

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=signmessagelib_address,
            value=ether_value,
            data=tx_data,
            safe_tx_gas=safe_tx_gas,
            operation=SafeOperation.DELEGATE_CALL.value,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"get_raw_safe_transaction_hash unsuccessful!: {contract_api_msg}"
            )
            return None, snapshot_api_data

        safe_tx_hash = cast(str, contract_api_msg.state.body["tx_hash"])
        safe_tx_hash = safe_tx_hash[2:]
        self.context.logger.info(f"Hash of the Safe transaction: {safe_tx_hash}")

        # temp hack:
        payload_string = hash_payload_to_hex(
            safe_tx_hash,
            ether_value,
            safe_tx_gas,
            signmessagelib_address,
            tx_data,
            SafeOperation.DELEGATE_CALL.value,
        )

        return payload_string, snapshot_api_data


class RetrieveSignatureBehaviour(ProposalVoterBaseBehaviour):
    """RetrieveSignatureBehaviour"""

    matching_round: Type[AbstractRound] = RetrieveSignatureRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            if not self.context.state.pending_vote.snapshot:
                payload_content = RetrieveSignatureRound.SKIP_PAYLOAD
            else:
                snapshot_api_data_signature = yield from self._get_safe_signature()
                payload_content = json.dumps(
                    {"snapshot_api_data_signature": snapshot_api_data_signature},
                    sort_keys=True,
                )

            sender = self.context.agent_address
            payload = RetrieveSignaturePayload(
                sender=sender,
                content=payload_content,
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _get_safe_signature(self):
        """Get signature from the chain"""

        self.context.logger.info(
            f"Retrieving signature from event for tx_hash={self.synchronized_data.final_tx_hash}"
        )

        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(SignMessageLibContract.contract_id),
            contract_callable="get_safe_signature",
            tx_hash=self.synchronized_data.final_tx_hash,
        )
        if (
            contract_api_msg.performative != ContractApiMessage.Performative.STATE
        ):  # pragma: nocover
            self.context.logger.warning(
                f"Could not get the transaction signature: {contract_api_msg}"
            )
            return None

        signature = cast(str, contract_api_msg.state.body["signature"])
        self.context.logger.info(f"Retrieved signature: {signature}")
        return signature


class SnapshotAPISendRandomnessBehaviour(RandomnessBehaviour):
    """Retrieve randomness."""

    matching_round = SnapshotAPISendRandomnessRound
    payload_class = SnapshotAPISendRandomnessPayload


class SnapshotAPISendSelectKeeperBehaviour(
    SelectKeeperBehaviour, ProposalVoterBaseBehaviour
):
    """Select the keeper agent."""

    matching_round = SnapshotAPISendSelectKeeperRound
    payload_class = SnapshotAPISendSelectKeeperPayload


class SnapshotAPISendBehaviour(ProposalVoterBaseBehaviour):
    """SnapshotAPISendBehaviour"""

    matching_round: Type[AbstractRound] = SnapshotAPISendRound

    def _i_am_not_sending(self) -> bool:
        """Indicates if the current agent is the sender or not."""
        return (
            self.context.agent_address
            != self.synchronized_data.most_voted_keeper_address
        )

    def async_act(self) -> Generator[None, None, None]:
        """Do the action"""
        if self._i_am_not_sending():
            yield from self._not_sender_act()
        else:
            yield from self._sender_act()

    def _not_sender_act(self) -> Generator:
        """Do the non-sender action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            self.context.logger.info(
                f"Waiting for the keeper to do its keeping: {self.synchronized_data.most_voted_keeper_address}"
            )
            yield from self.wait_until_round_end()
        self.set_done()

    def _sender_act(self) -> Generator:
        """Do the sender action"""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload_content = yield from self._call_snapshot_api()
            sender = self.context.agent_address
            payload = SnapshotAPISendPayload(sender=sender, content=payload_content)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def _call_snapshot_api(self):
        """Send the vote to Snapshot's API"""

        envelope = {
            "address": self.synchronized_data.safe_contract_address,
            "data": self.synchronized_data.snapshot_api_data,
            "sig": self.synchronized_data.snapshot_api_data_signature,
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Make the request
        response = yield from self.get_http_response(
            method="POST",
            url=self.params.snapshot_api_endpoint,
            content=json.dumps(envelope).encode("utf-8"),
            headers=headers,
        )

        if response.status_code != HTTP_OK:
            self.context.logger.error(
                f"Could not send the vote to Snapshot API. "
                f"Received status code {response.status_code}: {response.json()}."
            )
            return SnapshotAPISendRound.ERROR_PAYLOAD

        return SnapshotAPISendRound.SUCCCESS_PAYLOAD


class ProposalVoterRoundBehaviour(AbstractRoundBehaviour):
    """ProposalVoterRoundBehaviour"""

    initial_behaviour_cls = EstablishVoteBehaviour
    abci_app_cls = ProposalVoterAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [
        EstablishVoteBehaviour,
        PrepareVoteTransactionBehaviour,
        RetrieveSignatureBehaviour,
        SnapshotAPISendRandomnessBehaviour,
        SnapshotAPISendSelectKeeperBehaviour,
        SnapshotAPISendBehaviour,
    ]
