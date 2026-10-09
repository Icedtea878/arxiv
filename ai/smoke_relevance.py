"""Small paid provider check; never publishes sample papers to the site."""
import os
from langchain_openai import ChatOpenAI
from runtime import build_chat_openai_kwargs
from relevance import score_paper

llm = ChatOpenAI(timeout=120, max_retries=1, **build_chat_openai_kwargs(
    os.getenv('MODEL_NAME', 'MiniMax-M3'),
    os.getenv('OPENAI_BASE_URL', 'https://api.minimax.cn/v1'), os.getenv('OPENAI_API_KEY', '')))
fixtures = [
    ('individual', 'Simulating individual human choices', 'We model individual people using their histories and predict their choices in held-out situations.'),
    ('interaction', 'Modeling interpersonal negotiation', 'We simulate how people negotiate, infer each other intentions and adapt their dialogue and decisions during interpersonal interactions.'),
    ('group', 'Collective opinion dynamics', 'We simulate groups of people and validate emergent collective behavior and opinion change against human group experiments.'),
    ('society', 'Simulating social norms in a society', 'We model a population of social agents to simulate the emergence and diffusion of social norms and institutions across communities.'),
    (None, 'A fast matrix multiplication kernel', 'We optimize GPU matrix multiplication through memory tiling, evaluating floating point throughput on random matrices. No human or social behavior is modeled.'),
]
for direction, title, abstract in fixtures:
    result, usage = score_paper(llm, {'title': title, 'summary': abstract})
    print(direction or 'unrelated', result, usage, flush=True)
    if direction:
        assert result['score'] > 80 and direction in result['directions'], result
    else:
        assert result['score'] <= 80, result
print('Provider relevance check passed for all four directions and an unrelated control.')
