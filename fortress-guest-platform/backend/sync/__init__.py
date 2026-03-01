"""
Streamline Data Synapse — ETL facade over the production StreamlineVRS engine.

This package exposes a clean interface (StreamlineClient, SynapseDB, SyncWorker)
while delegating to the battle-tested sync engine in backend.integrations.streamline_vrs.
"""
from backend.sync.streamline_client import StreamlineClient
from backend.sync.db_upsert import SynapseDB
from backend.sync.worker import SyncWorker

__all__ = ["StreamlineClient", "SynapseDB", "SyncWorker"]
