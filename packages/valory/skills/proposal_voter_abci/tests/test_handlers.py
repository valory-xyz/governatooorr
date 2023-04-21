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

"""Test the handlers.py module of the GenericScoring."""

from packages.valory.protocols.llm import LlmMessage
from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.proposal_voter_abci.handlers import LlmHandler


def test_llm_handler():
    handler = LlmHandler(name="", skill_context=DummyContext())
    assert handler.SUPPORTED_PROTOCOL == LlmMessage.protocol_id
