# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This module contains the handlers for the skill of DynamicNFTAbciApp."""

import json
import re
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

from aea.protocols.base import Message

from packages.fetchai.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.proposal_collector_abci.dialogues import (
    HttpDialogue,
    HttpDialogues,
)
from packages.valory.skills.proposal_collector_abci.models import SharedState
from packages.valory.skills.proposal_collector_abci.rounds import SynchronizedData


ABCIRoundHandler = BaseABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler

OK_CODE = 200
NOT_FOUND_CODE = 404
BAD_REQUEST_CODE = 400
AVERAGE_PERIOD_SECONDS = 10


def delegation_to_camel_case(delegation):
    """Converts delegations to camel case"""
    return {
        "address": delegation["user_address"],
        "delegatedToken": delegation["token_address"],
        "votingPreference": delegation["voting_preference"],
        "governorAddress": delegation["governor_address"],
        "tokenBalance": delegation["delegated_amount"],
    }


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpHandler(BaseHttpHandler):
    """This implements the echo handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def setup(self) -> None:
        """Implement the setup."""
        service_endpoint_base = urlparse(
            self.context.params.service_endpoint_base
        ).hostname
        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        # Route regexes
        hostname_regex = rf".*({service_endpoint_base}|{propel_uri_base_hostname}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        self.handler_url_regex = rf"{hostname_regex}\/.*"
        eth_address_regex = r"0x[a-fA-F0-9]{40}"

        # Endpoint regexes
        delegate_url_regex = rf"{hostname_regex}\/delegate\/?$"
        delegations_url_regex = (
            rf"{hostname_regex}\/delegations\/{eth_address_regex}\/?$"
        )
        proposals_url_regex = rf"{hostname_regex}\/proposals\/?$"
        proposal_url_regex = rf"{hostname_regex}\/proposal\/\d+\/?$"
        health_url_regex = rf"{hostname_regex}\/healthcheck"

        # Routes
        self.routes = {
            (HttpMethod.POST.value,): [
                (delegate_url_regex, self._handle_post_delegate),
            ],
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                (delegations_url_regex, self._handle_get_delegations),
                (proposals_url_regex, self._handle_get_proposals),
                (proposal_url_regex, self._handle_get_proposal),
                (health_url_regex, self._handle_get_health),
            ],
        }

        self.json_content_header = "Content-Type: application/json\n"

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

    def _get_handler(self, url: str, method: str) -> Tuple[Optional[Callable], Dict]:
        """Check if an url is meant to be handled in this handler

        We expect url to match the pattern {hostname}/.*,
        where hostname is allowed to be localhost, 127.0.0.1 or the token_uri_base's hostname.
        Examples:
            localhost:8000/0
            127.0.0.1:8000/100
            https://pfp.staging.autonolas.tech/45
            http://pfp.staging.autonolas.tech/120

        :param url: the url to check
        :returns: the handling method if the message is intended to be handled by this handler, None otherwise, and the regex captures
        """
        # Check base url
        if not re.match(self.handler_url_regex, url):
            self.context.logger.info(
                f"The url {url} does not match the DynamicNFT HttpHandler's pattern"
            )
            return None, {}

        # Check if there is a route for this request
        for methods, routes in self.routes.items():
            if method not in methods:
                continue

            for route in routes:
                # Routes are tuples like (route_regex, handle_method)
                m = re.match(route[0], url)
                if m:
                    return route[1], m.groupdict()

        # No route found
        self.context.logger.info(
            f"The message [{method}] {url} is intended for the DynamicNFT HttpHandler but did not match any valid pattern"
        )
        return self._handle_bad_request, {}

    def handle(self, message: Message) -> None:
        """
        Implement the reaction to an envelope.

        :param message: the message
        """
        http_msg = cast(HttpMessage, message)

        # Check if this is a request sent from the http_server skill
        if (
            http_msg.performative != HttpMessage.Performative.REQUEST
            or message.sender != str(HTTP_SERVER_PUBLIC_ID.without_hash())
        ):
            super().handle(message)
            return

        # Check if this message is for this skill. If not, send to super()
        handler, kwargs = self._get_handler(http_msg.url, http_msg.method)
        if not handler:
            super().handle(message)
            return

        # Retrieve dialogues
        http_dialogues = cast(HttpDialogues, self.context.http_dialogues)
        http_dialogue = cast(HttpDialogue, http_dialogues.update(http_msg))

        # Invalid message
        if http_dialogue is None:
            self.context.logger.info(
                "Received invalid http message={}, unidentified dialogue.".format(
                    http_msg
                )
            )
            return

        # Handle message
        self.context.logger.info(
            "Received http request with method={}, url={} and body={!r}".format(
                http_msg.method,
                http_msg.url,
                http_msg.body,
            )
        )
        handler(http_msg, http_dialogue, **kwargs)

    def _handle_bad_request(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http bad request.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=BAD_REQUEST_CODE,
            status_text="Bad request",
            headers=http_msg.headers,
            body=b"",
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _handle_post_delegate(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        self.context.logger.info("Received delegation")

        delegation_data = json.loads(http_msg.body)  # TODO: is this ok?

        # Add the new delegation to this agent's new delegation list
        self.context.state.new_delegations.append(
            {
                "user_address": delegation_data["address"],
                "token_address": delegation_data["delegatedToken"],
                "voting_preference": delegation_data["votingPreference"].upper(),
                "governor_address": delegation_data["governorAddress"],
                "delegated_amount": int(delegation_data["tokenBalance"]),
            }
        )

        response_body_data = {}

        self._send_ok_response(http_msg, http_dialogue, response_body_data)

    def _handle_get_delegations(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        # Get the token address
        address = http_msg.url.split("/")[-1]

        delegations = [
            delegation_to_camel_case(d)
            for d in self.synchronized_data.delegations
            if d["user_address"] == address
        ]

        response_body_data = delegations

        self._send_ok_response(http_msg, http_dialogue, response_body_data)

    def _handle_get_proposals(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        response_body_data = list(self.synchronized_data.proposals.values())

        self._send_ok_response(http_msg, http_dialogue, response_body_data)

    def _handle_get_proposal(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        proposal_id = http_msg.url.split("/")[-1]
        proposal = (
            None
            if proposal_id not in self.synchronized_data.proposals
            else self.synchronized_data.proposals[proposal_id]
        )

        if not proposal:
            self._send_not_found_response(http_msg, http_dialogue)
            return

        response_body_data = proposal

        self._send_ok_response(http_msg, http_dialogue, response_body_data)

    def _send_ok_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[Dict, List],
    ) -> None:
        """Send an OK response with the provided data"""
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=OK_CODE,
            status_text="Success",
            headers=f"{self.json_content_header}{http_msg.headers}",
            body=json.dumps(data).encode("utf-8"),
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_not_found_response(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Send an not found response"""
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=NOT_FOUND_CODE,
            status_text="Not found",
            headers=http_msg.headers,
            body=b"",
        )
        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _handle_get_health(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http request of verb GET.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        seconds_since_last_transition = None
        is_tm_unhealthy = None
        is_transitioning_fast = None
        current_round = None
        previous_rounds = None

        round_sequence = cast(SharedState, self.context.state).round_sequence

        if round_sequence._last_round_transition_timestamp:
            is_tm_unhealthy = cast(
                SharedState, self.context.state
            ).round_sequence.block_stall_deadline_expired

            current_time = datetime.now().timestamp()
            seconds_since_last_transition = current_time - datetime.timestamp(
                round_sequence._last_round_transition_timestamp
            )

            is_transitioning_fast = (
                not is_tm_unhealthy
                and seconds_since_last_transition
                < 2 * self.context.params.reset_pause_duration
            )

        if round_sequence._abci_app:
            current_round = round_sequence._abci_app.current_round.round_id
            previous_rounds = [
                r.round_id for r in round_sequence._abci_app._previous_rounds[-10:]
            ]

        data = {
            "seconds_since_last_transition": seconds_since_last_transition,
            "is_tm_healthy": not is_tm_unhealthy,
            "period": self.synchronized_data.period_count,
            "reset_pause_duration": self.context.params.reset_pause_duration,
            "current_round": current_round,
            "previous_rounds": previous_rounds,
            "is_transitioning_fast": is_transitioning_fast,
        }

        self._send_ok_response(http_msg, http_dialogue, data)
