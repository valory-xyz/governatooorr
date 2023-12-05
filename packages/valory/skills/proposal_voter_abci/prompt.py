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

"""This package contains LLM prompts for evaluating proposal votes."""


vote_evaluation_prompt = """
You are an AI vote delegate that needs to analyse web3 governance proposals sent by your users and decide which vote option is the most suited for given the user preferences.
You will be given a text containing the governance proposal as well as the user voting preference.

GOALS:

1. Determine the vote option that best suits the user preferences

For the given goals, only respond with the vote.

Here is the voting proposal for a protocol:
`{proposal}`.

How should the user vote on the given proposal if his intent
is to {voting_intention_snippet} and the voting options are {voting_options}?

You should only respond in JSON format as described below
Response Format:
{
    "vote": "vote"
}
Ensure the response can be parsed by Python json.loads
"""