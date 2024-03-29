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

"""This package contains the queries for Tally."""


proposal_query = """
query Proposals(
  $chainId: ChainID!
  $proposers: [Address!],
  $governors: [Address!],
  $pagination: Pagination
) {
  proposals(
    chainId: $chainId
    proposers: $proposers
    governors: $governors
    pagination: $pagination
) {
    id
    title
    description
    end {
      number
    }
    proposer {
      address
    }
    governor {
      id
      type
      name
      tokens {
        id
      }
    }
    eta
    voteStats {
      support
    }
    statusChanges {
        type
    }
  }
}
"""

governor_query = """
query Governors(
  $chainIds: [ChainID!],
  $addresses: [Address!],
  $ids: [AccountID!],
  $includeInactive: Boolean,
  $pagination: Pagination,
  $sort: GovernorSort
) {
  governors(
    chainIds: $chainIds,
    addresses: $addresses,
    ids: $ids,
    includeInactive: $includeInactive,
    pagination: $pagination,
    sort: $sort
  ) {
    id
    type
    name
    slug
    proposalStats {
      total
      active
      failed
      passed
    }
  }
}
"""
