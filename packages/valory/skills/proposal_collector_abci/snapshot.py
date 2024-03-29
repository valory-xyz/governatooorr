# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This package contains the queries for Snapshot."""


snapshot_proposal_query = """
query Proposals(
  $first: Int
  $skip: Int
  $space_in: [String]
) {
  proposals (
    first: $first,
    skip: $skip,
    where: {
      state: "active",
      space_in: $space_in
    },
    orderBy: "end",
    orderDirection: asc
  ) {
    id
    network
    title
    body
    choices
    start
    end
    snapshot
    state
    space {
      id
      name
      symbol
    }
    strategies {
      name
    }
    flagged
  }
}
"""

snapshot_vp_query = """
query Vp(
  $voter: String!
  $space: String!
  $proposal: String!
) {
  vp (
    voter: $voter
    space: $space
    proposal: $proposal
  ) {
    vp
    vp_state
  }
}
"""
