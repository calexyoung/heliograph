#!/bin/bash
cd /Users/cayoung/Developer/heliograph

# Ensure OPENAI_API_KEY is set in environment
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable is not set"
    exit 1
fi

python scripts/test_langchain_extractor.py
