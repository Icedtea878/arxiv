"""Check that the configured provider supports the paper summary schema."""

import os

from langchain_openai import ChatOpenAI

from model_config import get_base_url, get_model
from runtime import build_chat_openai_kwargs
from structure import Structure


def main() -> None:
    model = ChatOpenAI(
        **build_chat_openai_kwargs(
            model_name=get_model("reader"),
            base_url=get_base_url(),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )
    ).with_structured_output(Structure, method="function_calling")
    result = model.invoke(
        "In Chinese, summarize this research abstract using the requested fields: "
        "We introduce a small benchmark for evaluating document retrieval. "
        "On a held-out set of 100 queries, the new method improves recall by 8%."
    )
    if not isinstance(result, Structure) or not all(str(value).strip() for value in result.model_dump().values()):
        raise RuntimeError("Provider returned an incomplete structured summary")
    print("Provider accepted the key and returned all five summary fields.")


if __name__ == "__main__":
    main()
