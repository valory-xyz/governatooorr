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
from packages.valory.skills.ceramic_read_abci.behaviours import (
    CeramicReadRoundBehaviour,
)
from packages.valory.skills.ceramic_write_abci.behaviours import (
    CeramicWriteRoundBehaviour,
)
from packages.valory.skills.governatooorr_abci.composition import GovernatooorrAbciApp
from packages.valory.skills.mech_interact_abci.behaviours.round_behaviour import (
    MechInteractRoundBehaviour,
)
from packages.valory.skills.proposal_collector_abci.behaviours import (
    ProposalCollectorRoundBehaviour,
)
from packages.valory.skills.proposal_voter_abci.behaviours import (
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
from packages.valory.skills.transaction_settlement_abci.behaviours import (
    TransactionSettlementRoundBehaviour,
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
        *TransactionSettlementRoundBehaviour.behaviours,
        *TerminationAbciBehaviours.behaviours,
        *CeramicReadRoundBehaviour.behaviours,
        *CeramicWriteRoundBehaviour.behaviours,
        *MechInteractRoundBehaviour.behaviours,
    }
    background_behaviours_cls = {BackgroundBehaviour}
