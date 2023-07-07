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

"""This package contains round behaviours of Governatooorr."""

from typing import Set, Type

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.governatooorr_solana_abci.composition import (
    GovernatooorrAbciApp,
)
from packages.valory.skills.proposal_collector_solana_abci.behaviours import (
    ProposalCollectorRoundBehaviour,
)
from packages.valory.skills.proposal_voter_solana_abci.behaviours import (
    ProposalVoterRoundBehaviour,
)
from packages.valory.skills.registration_abci.behaviours import (
    AgentRegistrationRoundBehaviour,
    RegistrationStartupBehaviour,
)
from packages.valory.skills.reset_pause_abci.behaviours import (
    ResetPauseABCIConsensusBehaviour,
)
from packages.valory.skills.termination_abci.behaviours import (
    BackgroundBehaviour,
    TerminationAbciBehaviours,
)
from packages.valory.skills.solana_transaction_settlement_abci.behaviours import (
    SolanaTransactionSettlementRoundBehaviour,
)


class GovernatooorrConsensusBehaviour(AbstractRoundBehaviour):
    """Class to define the behaviours this AbciApp has."""

    initial_behaviour_cls = RegistrationStartupBehaviour
    abci_app_cls = GovernatooorrAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        *ProposalCollectorRoundBehaviour.behaviours,
        *ProposalVoterRoundBehaviour.behaviours,
        *AgentRegistrationRoundBehaviour.behaviours,
        *ResetPauseABCIConsensusBehaviour.behaviours,
        *SolanaTransactionSettlementRoundBehaviour.behaviours,
        *TerminationAbciBehaviours.behaviours,
    }
    background_behaviour_cls = BackgroundBehaviour
