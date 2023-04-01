# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 valory
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

"""OpenAI connection and channel."""

from typing import Any, Dict, cast

from aea.configurations.base import PublicId
from aea.connections.base import BaseSyncConnection
from aea.mail.base import Envelope
from aea.protocols.base import Address, Message
from aea.protocols.dialogue.base import Dialogue

import openai

from packages.valory.protocols.llm.dialogues import (
    LlmDialogues as BaseLlmDialogues,
    LlmDialogue,
)
from packages.valory.protocols.llm.message import LlmMessage

CONNECTION_ID = PublicId.from_str("valory/openai:0.1.0")


class LlmDialogues(BaseLlmDialogues):
    """A class to keep track of IPFS dialogues."""

    def __init__(self, **kwargs: Any) -> None:
        """
        Initialize dialogues.

        :param kwargs: keyword arguments
        """

        def role_from_first_message(  # pylint: disable=unused-argument
            message: Message, receiver_address: Address
        ) -> Dialogue.Role:
            """Infer the role of the agent from an incoming/outgoing first message

            :param message: an incoming/outgoing first message
            :param receiver_address: the address of the receiving agent
            :return: The role of the agent
            """
            return LlmDialogue.Role.CONNECTION

        BaseLlmDialogues.__init__(
            self,
            self_address=str(kwargs.pop("connection_id")),
            role_from_first_message=role_from_first_message,
            **kwargs,
        )


class OpenaiConnection(BaseSyncConnection):
    """Proxy to the functionality of the openai SDK."""

    MAX_WORKER_THREADS = 1

    connection_id = CONNECTION_ID

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        """
        Initialize the connection.

        The configuration must be specified if and only if the following
        parameters are None: connection_id, excluded_protocols or restricted_to_protocols.

        Possible arguments:
        - configuration: the connection configuration.
        - data_dir: directory where to put local files.
        - identity: the identity object held by the agent.
        - crypto_store: the crypto store for encrypted communication.
        - restricted_to_protocols: the set of protocols ids of the only supported protocols for this connection.
        - excluded_protocols: the set of protocols ids that we want to exclude for this connection.

        :param args: arguments passed to component base
        :param kwargs: keyword arguments passed to component base
        """
        super().__init__(*args, **kwargs)
        self.openai_settings = {
            setting: self.configuration.config.get(setting)
            for setting in ("openai_api_key", "engine", "max_tokens", "temperature")
        }
        openai.api_key = self.openai_settings["openai_api_key"]
        self.dialogues = LlmDialogues(connection_id=CONNECTION_ID)

    def main(self) -> None:
        """
        Run synchronous code in background.

        SyncConnection `main()` usage:
        The idea of the `main` method in the sync connection
        is to provide for a way to actively generate messages by the connection via the `put_envelope` method.

        A simple example is the generation of a message every second:
        ```
        while self.is_connected:
            envelope = make_envelope_for_current_time()
            self.put_enevelope(envelope)
            time.sleep(1)
        ```
        In this case, the connection will generate a message every second
        regardless of envelopes sent to the connection by the agent.
        For instance, this way one can implement periodically polling some internet resources
        and generate envelopes for the agent if some updates are available.
        Another example is the case where there is some framework that runs blocking
        code and provides a callback on some internal event.
        This blocking code can be executed in the main function and new envelops
        can be created in the event callback.
        """

    def on_send(self, envelope: Envelope) -> None:
        """
        Send an envelope.

        :param envelope: the envelope to send.
        """
        llm_message = cast(LlmMessage, envelope.message)

        dialogue = self.dialogues.update(llm_message)

        if llm_message.performative != LlmMessage.Performative.REQUEST:
            self.logger.error(
                f"Performative `{llm_message.performative.value}` is not supported."
            )
            return

        vote = self._get_vote(
            prompt_template=llm_message.prompt_template,
            prompt_values=llm_message.prompt_values,
        )
        self.logger.info(f"Vote: {vote}")

        response_message = cast(
            LlmMessage,
            dialogue.reply(
                performative=LlmMessage.Performative.RESPONSE,
                target_message=llm_message,
                value=vote,
            ),
        )

        response_envelope = Envelope(
            to=envelope.sender,
            sender=envelope.to,
            message=response_message,
            context=envelope.context,
        )

        self.put_envelope(response_envelope)

    def _get_vote(self, prompt_template: str, prompt_values: Dict[str, str]):
        """Get vote."""
        # Format the prompt using input variables and prompt_values
        formatted_prompt = prompt_template.format(**prompt_values)

        # Call the OpenAI API
        response = openai.Completion.create(
            engine=self.openai_settings["engine"],
            prompt=formatted_prompt,
            max_tokens=self.openai_settings["max_tokens"],
            n=1,
            stop=None,
            temperature=self.openai_settings["temperature"],
        )

        # Extract the result from the API response
        result = response.choices[0].text

        return result

    def on_connect(self) -> None:
        """
        Tear down the connection.

        Connection status set automatically.
        """

    def on_disconnect(self) -> None:
        """
        Tear down the connection.

        Connection status set automatically.
        """