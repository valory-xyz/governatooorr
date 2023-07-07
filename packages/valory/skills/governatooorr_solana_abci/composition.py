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

"""This package contains round behaviours of GovernatooorrAbciApp."""

import packages.valory.skills.proposal_collector_solana_abci.rounds as ProposalCollectorSolanaAbciApp
import packages.valory.skills.proposal_voter_solana_abci.rounds as ProposalVoterSolanaAbciApp
import packages.valory.skills.registration_abci.rounds as RegistrationAbci
import packages.valory.skills.reset_pause_abci.rounds as ResetAndPauseAbci
import packages.valory.skills.solana_transaction_settlement_abci.rounds as SolanaTransactionSubmissionAbciApp
from packages.valory.skills.abstract_round_abci.abci_app_chain import (
    AbciAppTransitionMapping,
    chain,
)
from packages.valory.skills.termination_abci.rounds import BackgroundRound
from packages.valory.skills.termination_abci.rounds import Event as TerminationEvent
from packages.valory.skills.termination_abci.rounds import TerminationAbciApp


# Here we define how the transition between the FSMs should happen
# more information here: https://docs.autonolas.network/fsm_app_introduction/#composition-of-fsm-apps
abci_app_transition_mapping: AbciAppTransitionMapping = {
    RegistrationAbci.FinishedRegistrationRound: ProposalCollectorSolanaAbciApp.CollectActiveRealmsProposalsRound,
    ProposalCollectorSolanaAbciApp.FinishedCollectRealmsProposalRound: ProposalVoterSolanaAbciApp.EstablishVoteRound,
    ProposalVoterSolanaAbciApp.FinishedTransactionPreparationNoVoteRound: ResetAndPauseAbci.ResetAndPauseRound,
    ProposalVoterSolanaAbciApp.FinishedTransactionPreparationVoteRound: SolanaTransactionSubmissionAbciApp.CreateTxRandomnessRound,
    SolanaTransactionSubmissionAbciApp.FinishedTransactionSubmissionRound: ProposalVoterSolanaAbciApp.PrepareVoteTransactionRound,
    SolanaTransactionSubmissionAbciApp.FailedRound: ProposalVoterSolanaAbciApp.PrepareVoteTransactionRound,
    ResetAndPauseAbci.FinishedResetAndPauseRound: ProposalCollectorSolanaAbciApp.CollectActiveRealmsProposalsRound,
    ResetAndPauseAbci.FinishedResetAndPauseErrorRound: RegistrationAbci.RegistrationRound,
}

GovernatooorrAbciApp = chain(
    (
        RegistrationAbci.AgentRegistrationAbciApp,
        ProposalCollectorSolanaAbciApp.ProposalCollectorSolanaAbciApp,
        ProposalVoterSolanaAbciApp.ProposalVoterSolanaAbciApp,
        ResetAndPauseAbci.ResetPauseAbciApp,
        SolanaTransactionSubmissionAbciApp.SolanaTransactionSubmissionAbciApp,
    ),
    abci_app_transition_mapping,
).add_termination(
    background_round_cls=BackgroundRound,
    termination_event=TerminationEvent.TERMINATE,
    termination_abci_app=TerminationAbciApp,
)
