from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from .clock import Clock
from .config import Settings
from .crypto import Signer
from .merchant import MockMerchant


@dataclass
class Runtime:
    settings: Settings
    sessions: sessionmaker[Session]
    signer: Signer
    merchant: MockMerchant
    clock: Clock
