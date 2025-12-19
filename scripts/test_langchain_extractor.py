#!/usr/bin/env python3
"""Test script for LangChain-based knowledge graph extraction.

This script tests the LangChain extractor with sample heliophysics text.

Usage:
    pip install langchain-experimental langchain-openai python-dotenv
    python scripts/test_langchain_extractor.py
"""

import asyncio
import os
import sys
from uuid import uuid4

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, ".env"))
except ImportError:
    pass  # dotenv not required if env vars are set


# Sample heliophysics text for testing
SAMPLE_TEXT = """
Solar flares are sudden, intense bursts of radiation emanating from the Sun's surface,
particularly from active regions near sunspots. These events release enormous amounts of
energy across the electromagnetic spectrum, from radio waves to gamma rays.

The Solar Dynamics Observatory (SDO), launched by NASA in 2010, has been instrumental
in studying solar flares and their effects. SDO's Atmospheric Imaging Assembly (AIA)
captures images of the Sun in multiple wavelengths, allowing scientists to observe the
dynamics of solar flares in unprecedented detail.

Coronal mass ejections (CMEs) are often associated with solar flares. When a CME reaches
Earth, it can cause geomagnetic storms that affect satellite communications, power grids,
and produce auroras visible at lower latitudes. The Advanced Composition Explorer (ACE)
spacecraft, positioned at the L1 Lagrange point, provides early warning of incoming CMEs.

The Parker Solar Probe, launched in 2018, is designed to study the solar corona and
solar wind at closer distances than any previous spacecraft. Its measurements are helping
scientists understand the mechanisms that heat the corona to millions of degrees and
accelerate the solar wind to supersonic speeds.

Magnetic reconnection is the fundamental process driving solar flares. During reconnection,
magnetic field lines break and reconnect, converting magnetic energy into kinetic energy
and heat. The Magnetospheric Multiscale (MMS) mission studies this process in Earth's
magnetosphere, providing insights applicable to solar physics.
"""


async def test_langchain_extractor():
    """Test the LangChain graph extractor."""
    print("=" * 60)
    print("Testing LangChain Knowledge Graph Extractor")
    print("=" * 60)

    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("\nError: OPENAI_API_KEY environment variable not set")
        print("Please set it with: export OPENAI_API_KEY=your_key")
        return

    try:
        from langchain_experimental.graph_transformers import LLMGraphTransformer
        from langchain_openai import ChatOpenAI
        from langchain_core.documents import Document
    except ImportError as e:
        print(f"\nError: LangChain dependencies not installed: {e}")
        print("Install with: pip install langchain-experimental langchain-openai langchain-core")
        return

    print("\n1. Initializing LLM and Graph Transformer...")

    # Initialize with heliophysics constraints
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Heliophysics-specific node types
    allowed_nodes = [
        "ScientificConcept",
        "Method",
        "Dataset",
        "Instrument",
        "Phenomenon",
        "Mission",
        "Spacecraft",
        "CelestialBody",
        "Organization",
        "Person",
    ]

    # Create constrained transformer
    transformer = LLMGraphTransformer(
        llm=llm,
        allowed_nodes=allowed_nodes,
    )

    print(f"   - Model: gpt-4o-mini")
    print(f"   - Allowed node types: {len(allowed_nodes)}")

    print("\n2. Extracting knowledge graph from sample text...")
    print(f"   - Text length: {len(SAMPLE_TEXT)} characters")

    # Convert text to document
    doc = Document(page_content=SAMPLE_TEXT)

    # Extract graph
    graph_documents = transformer.convert_to_graph_documents([doc])

    if not graph_documents:
        print("   - No graph documents returned")
        return

    graph_doc = graph_documents[0]
    nodes = graph_doc.nodes
    relationships = graph_doc.relationships

    print(f"\n3. Extraction Results:")
    print(f"   - Nodes extracted: {len(nodes)}")
    print(f"   - Relationships extracted: {len(relationships)}")

    # Display nodes
    print("\n4. Extracted Nodes:")
    print("-" * 50)
    node_types = {}
    for node in nodes:
        node_type = node.type
        node_types[node_type] = node_types.get(node_type, 0) + 1
        print(f"   [{node_type}] {node.id}")

    print("\n   Node type distribution:")
    for ntype, count in sorted(node_types.items()):
        print(f"   - {ntype}: {count}")

    # Display relationships
    print("\n5. Extracted Relationships:")
    print("-" * 50)
    rel_types = {}
    for rel in relationships:
        rel_type = rel.type
        rel_types[rel_type] = rel_types.get(rel_type, 0) + 1
        print(f"   {rel.source.id} --[{rel_type}]--> {rel.target.id}")

    print("\n   Relationship type distribution:")
    for rtype, count in sorted(rel_types.items()):
        print(f"   - {rtype}: {count}")

    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)

    # Now test our wrapper
    print("\n\n" + "=" * 60)
    print("Testing HelioGraph LangChain Extractor Wrapper")
    print("=" * 60)

    try:
        from services.knowledge_extraction.app.config import Settings
        from services.knowledge_extraction.app.extractors.langchain_extractor import (
            LangChainGraphExtractor,
            HybridExtractor,
        )

        # Create settings with LangChain enabled
        settings = Settings(
            USE_LANGCHAIN_EXTRACTOR=True,
            CONSTRAINED_EXTRACTION=True,
            OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        )

        print("\n1. Testing LangChainGraphExtractor...")
        extractor = LangChainGraphExtractor(settings)

        chunk_id = uuid4()
        document_id = uuid4()

        entities, relationships = await extractor.extract(
            SAMPLE_TEXT, chunk_id, document_id
        )

        print(f"   - Entities: {len(entities)}")
        print(f"   - Relationships: {len(relationships)}")

        print("\n   Extracted entities:")
        for entity in entities[:10]:  # Show first 10
            print(f"   - [{entity.entity_type.value}] {entity.name}")

        if len(entities) > 10:
            print(f"   ... and {len(entities) - 10} more")

        print("\n   Extracted relationships:")
        for rel in relationships[:10]:  # Show first 10
            print(f"   - {rel.source_entity} --[{rel.relationship_type.value}]--> {rel.target_entity}")

        if len(relationships) > 10:
            print(f"   ... and {len(relationships) - 10} more")

        print("\n" + "=" * 60)
        print("HelioGraph wrapper test completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError testing HelioGraph wrapper: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_langchain_extractor())
