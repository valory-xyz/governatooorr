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

"""This package contains payload tests for the GenericScoringAbciApp."""

from packages.valory.skills.proposal_voter_abci.payloads import (
    EstablishVotePayload,
    PrepareVoteTransactionPayload,
)


def test_establish_vote_payload() -> None:
    """Test `EstablishVotePayload`."""

    payload = EstablishVotePayload(sender="sender", proposals="proposals")

    assert payload.sender == "sender"
    assert payload.proposals == "proposals"
    assert payload.data == {"proposals": "proposals"}


def test_prepare_vote_payload() -> None:
    """Test `PrepareVoteTransactionPayload`."""

    payload = PrepareVoteTransactionPayload(sender="sender", content="content")

    assert payload.sender == "sender"
    assert payload.content == "content"
    assert payload.data == {"content": "content"}
