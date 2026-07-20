"""
Mock seed database of known AI startups for entity resolution, per Phase IV's
"mock a small database of 50 known AI startups" requirement.

Each canonical name maps to a list of real-world name variations that
commonly appear in scraped text — legal suffixes, spacing differences,
punctuation, and common shorthand. This is what lets "OpenAI, Inc." and
"Open AI" both resolve to the canonical "OpenAI".
"""
from __future__ import annotations

CANONICAL_STARTUPS: dict[str, list[str]] = {
    "OpenAI": ["OpenAI, Inc.", "Open AI", "OpenAI Inc", "OpenAI Inc.", "openai.com"],
    "Anthropic": ["Anthropic PBC", "Anthropic, Inc.", "Anthropic Inc"],
    "Google DeepMind": ["DeepMind", "Google Deepmind", "DeepMind Technologies"],
    "Cohere": ["Cohere Inc", "Cohere AI", "Cohere Technologies"],
    "Mistral AI": ["Mistral", "MistralAI"],
    "Stability AI": ["Stability", "Stability.ai", "StabilityAI"],
    "Hugging Face": ["HuggingFace", "Hugging Face Inc", "Hugging Face, Inc."],
    "Scale AI": ["Scale", "ScaleAI", "Scale.ai"],
    "Perplexity AI": ["Perplexity", "Perplexity.ai"],
    "Character.AI": ["Character AI", "CharacterAI"],
    "Inflection AI": ["Inflection", "Inflection.ai"],
    "Adept AI": ["Adept", "Adept AI Labs"],
    "Runway": ["Runway AI", "Runway ML", "RunwayML"],
    "ElevenLabs": ["Eleven Labs", "11Labs", "11 Labs"],
    "Midjourney": ["Midjourney Inc", "Midjourney, Inc."],
    "Replit": ["Repl.it", "Replit Inc"],
    "Databricks": ["Databricks Inc", "Databricks, Inc."],
    "Weights & Biases": ["Weights and Biases", "WandB", "W&B"],
    "LangChain": ["Lang Chain", "LangChain AI"],
    "Pinecone": ["Pinecone Systems", "Pinecone.io"],
    "Together AI": ["Together", "Together Computer"],
    "Groq": ["Groq Inc", "Groq, Inc."],
    "Cerebras": ["Cerebras Systems"],
    "SambaNova": ["SambaNova Systems"],
    "Cursor": ["Anysphere", "Anysphere Inc"],
    "Glean": ["Glean Technologies", "Glean Work"],
    "Harvey": ["Harvey AI", "Harvey.ai"],
    "Sierra": ["Sierra AI", "Sierra.ai"],
    "Writer": ["Writer AI", "Writer.com", "Qordoba"],
    "Jasper": ["Jasper AI", "Jasper.ai"],
    "Synthesia": ["Synthesia Ltd", "Synthesia.io"],
    "Tavus": ["Tavus Inc", "Tavus.io"],
    "Suno": ["Suno AI", "Suno.ai"],
    "Udio": ["Udio AI", "Udio.com"],
    "Luma AI": ["Luma", "Luma Labs"],
    "Pika": ["Pika Labs", "Pika.art"],
    "Ideogram": ["Ideogram AI", "Ideogram.ai"],
    "Black Forest Labs": ["BlackForestLabs", "Black Forest Labs Inc"],
    "Krea AI": ["Krea", "Krea.ai"],
    "Codeium": ["Codeium Inc", "Exafunction"],
    "Magic": ["Magic AI", "Magic.dev"],
    "Imbue": ["Imbue AI", "Generally Intelligent"],
    "Reflection AI": ["Reflection", "Reflection.ai"],
    "xAI": ["X.AI", "X AI Corp"],
    "Figure AI": ["Figure", "Figure Robotics"],
    "Physical Intelligence": ["Physical Intelligence Inc", "Pi Robotics"],
    "Skild AI": ["Skild", "Skild.ai"],
    "World Labs": ["World Labs Inc"],
    "Decagon": ["Decagon AI", "Decagon.ai"],
    "Clay": ["Clay Labs", "Clay.com"],
    "Abridge": ["Abridge AI", "Abridge.com"],
}