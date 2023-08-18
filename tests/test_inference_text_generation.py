# Original implementation taken from the `text-generation` Python client (see https://pypi.org/project/text-generation/
# and https://github.com/huggingface/text-generation-inference/tree/main/clients/python)
#
# See './src/huggingface_hub/inference/_text_generation.py' for details.
import unittest
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from requests import HTTPError

from huggingface_hub import InferenceClient
from huggingface_hub.inference._common import _NON_TGI_SERVERS
from huggingface_hub.inference._text_generation import (
    FinishReason,
    GenerationError,
    IncompleteGenerationError,
    InputToken,
    OverloadedError,
    TextGenerationParameters,
    TextGenerationRequest,
    raise_text_generation_error,
)
from huggingface_hub.inference._text_generation import (
    ValidationError as TextGenerationValidationError,
)


class TestTextGenerationTypes(unittest.TestCase):
    def test_parameters_validation(self):
        # Test best_of
        TextGenerationParameters(best_of=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(best_of=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(best_of=-1)
        TextGenerationParameters(best_of=2, do_sample=True)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(best_of=2)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(best_of=2, seed=1)

        # Test repetition_penalty
        TextGenerationParameters(repetition_penalty=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(repetition_penalty=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(repetition_penalty=-1)

        # Test seed
        TextGenerationParameters(seed=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(seed=-1)

        # Test temperature
        TextGenerationParameters(temperature=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(temperature=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(temperature=-1)

        # Test top_k
        TextGenerationParameters(top_k=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(top_k=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(top_k=-1)

        # Test top_p
        TextGenerationParameters(top_p=0.5)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(top_p=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(top_p=-1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(top_p=1)

        # Test truncate
        TextGenerationParameters(truncate=1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(truncate=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(truncate=-1)

        # Test typical_p
        TextGenerationParameters(typical_p=0.5)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(typical_p=0)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(typical_p=-1)
        with self.assertRaises(ValidationError):
            TextGenerationParameters(typical_p=1)

    def test_request_validation(self):
        TextGenerationRequest(inputs="test")

        with self.assertRaises(ValidationError):
            TextGenerationRequest(inputs="")

        TextGenerationRequest(inputs="test", stream=True)
        TextGenerationRequest(inputs="test", parameters=TextGenerationParameters(best_of=2, do_sample=True))

        with self.assertRaises(ValidationError):
            TextGenerationRequest(
                inputs="test", parameters=TextGenerationParameters(best_of=2, do_sample=True), stream=True
            )


class TestTextGenerationErrors(unittest.TestCase):
    def test_generation_error(self):
        error = _mocked_error({"error_type": "generation", "error": "test"})
        with self.assertRaises(GenerationError):
            raise_text_generation_error(error)

    def test_incomplete_generation_error(self):
        error = _mocked_error({"error_type": "incomplete_generation", "error": "test"})
        with self.assertRaises(IncompleteGenerationError):
            raise_text_generation_error(error)

    def test_overloaded_error(self):
        error = _mocked_error({"error_type": "overloaded", "error": "test"})
        with self.assertRaises(OverloadedError):
            raise_text_generation_error(error)

    def test_validation_error(self):
        error = _mocked_error({"error_type": "validation", "error": "test"})
        with self.assertRaises(TextGenerationValidationError):
            raise_text_generation_error(error)


def _mocked_error(payload: Dict) -> MagicMock:
    error = HTTPError(response=MagicMock())
    error.response.json.return_value = payload
    return error


@pytest.mark.vcr
@patch.dict("huggingface_hub.inference._common._NON_TGI_SERVERS", {})
class TestTextGenerationClientVCR(unittest.TestCase):
    """Use VCR test to avoid making requests to the prod infra."""

    def setUp(self) -> None:
        self.client = InferenceClient(model="google/flan-t5-xxl")
        return super().setUp()

    def test_generate_no_details(self):
        response = self.client.text_generation("test", details=False, max_new_tokens=1)

        assert response == ""

    def test_generate_with_details(self):
        response = self.client.text_generation("test", details=True, max_new_tokens=1, decoder_input_details=True)

        assert response.generated_text == ""
        assert response.details.finish_reason == FinishReason.Length
        assert response.details.generated_tokens == 1
        assert response.details.seed is None
        assert len(response.details.prefill) == 1
        assert response.details.prefill[0] == InputToken(id=0, text="<pad>", logprob=None)
        assert len(response.details.tokens) == 1
        assert response.details.tokens[0].id == 3
        assert response.details.tokens[0].text == " "
        assert not response.details.tokens[0].special

    def test_generate_best_of(self):
        response = self.client.text_generation(
            "test", max_new_tokens=1, best_of=2, do_sample=True, decoder_input_details=True, details=True
        )

        assert response.details.seed is not None
        assert response.details.best_of_sequences is not None
        assert len(response.details.best_of_sequences) == 1
        assert response.details.best_of_sequences[0].seed is not None

    def test_generate_validation_error(self):
        with self.assertRaises(TextGenerationValidationError):
            self.client.text_generation("test", max_new_tokens=10_000)

    def test_generate_stream_no_details(self):
        responses = list(
            self.client.text_generation(
                "test", max_new_tokens=1, stream=True, details=True
            )
        )

        assert len(responses) == 1
        response = responses[0]

        assert response.generated_text == ""
        assert response.details.finish_reason == FinishReason.Length
        assert response.details.generated_tokens == 1
        assert response.details.seed is None

    def test_generate_stream_with_details(self):
        responses = list(
            self.client.text_generation(
                "test", max_new_tokens=1, stream=True, details=True
            )
        )

        assert len(responses) == 1
        response = responses[0]

        assert response.generated_text == ""
        assert response.details.finish_reason == FinishReason.Length
        assert response.details.generated_tokens == 1
        assert response.details.seed is None

    def test_generate_non_tgi_endpoint(self):
        text = self.client.text_generation("0 1 2", model="gpt2", max_new_tokens=10)
        self.assertEqual(text, " 3 4 5 6 7 8 9 10 11 12")
        self.assertIn("gpt2", _NON_TGI_SERVERS)

        # Watermark is ignored (+ warning)
        with self.assertWarns(UserWarning):
            self.client.text_generation("4 5 6", model="gpt2", max_new_tokens=10, watermark=True)

        # Return as detail even if details=True (+ warning)
        with self.assertWarns(UserWarning):
            text = self.client.text_generation("0 1 2", model="gpt2", max_new_tokens=10, details=True)
            self.assertIsInstance(text, str)

        # Return as stream raises error
        with self.assertRaises(ValueError):
            self.client.text_generation("0 1 2", model="gpt2", max_new_tokens=10, stream=True)
