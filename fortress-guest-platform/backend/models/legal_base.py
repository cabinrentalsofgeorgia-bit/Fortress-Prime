"""
Isolated SQLAlchemy base for legal-domain tables.
"""
from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base


LegalBase = declarative_base(metadata=MetaData(schema="legal"))
