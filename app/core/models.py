"""
Data shapes (Pydantic) passed between pipeline steps. No logic here.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Intent(str, Enum):
    """What the user wants."""
    RECOMMEND = "recommend"
    CARD_DETAILS = "card_details"
    COMPARE = "compare"
    ELIGIBILITY = "eligibility"
    REFUSE = "refuse"
    UNKNOWN = "unknown"


class Spend(BaseModel):
    """Spending on one key. amount is in the server's unit for that key (from its name)."""
    key: str                           # server spending key, e.g. "amazon_spends"
    amount: int                        # in the key's unit (monthly / annual)
    unit: str                          # "month" | "year" | "quarter"
    annual_amount: int                 # yearly total, for display


class LooseAmount(BaseModel):
    """An amount whose category the code could not tell; the server's resolver is asked."""
    amount: int
    period: Optional[str] = None       # "month" / "year" if the user said so
    snippet: str                       # text around the amount


class Slots(BaseModel):
    """Facts taken from the user's message (and earlier answers)."""
    spends: list[Spend] = Field(default_factory=list)
    loose_amounts: list[LooseAmount] = Field(default_factory=list)
    mentioned_keys: list[str] = Field(default_factory=list)   # category mentioned without an amount ("card for fuel")
    card_names: list[str] = Field(default_factory=list)
    card_ids: list[str] = Field(default_factory=list)
    monthly_income: Optional[int] = None
    employment: Optional[str] = None   # server value: "salaried" / "self_employed"
    pincode: Optional[str] = None

    @property
    def total_annual_spend(self) -> Optional[int]:
        return sum(s.annual_amount for s in self.spends) if self.spends else None


class GuardResult(BaseModel):
    blocked: bool
    reason: Optional[str] = None       # for logs
    user_message: Optional[str] = None


class ValidationFlag(BaseModel):
    """A suspicious issue found in server data."""
    field: str
    problem: str
    suspected_fault: str               # "mcp_tool" | "data"
    warn_user: bool = True             # False = evidence only (trace), no warning to the user


class ToolCallRecord(BaseModel):
    """Record of one MCP call: evidence."""
    tool: str
    arguments: dict[str, Any]
    raw_response: Any
    ok: bool
    error: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class Metric(BaseModel):
    """One line on a card: label + server text (bracketed part kept separately)."""
    key: str
    label: str
    value: str
    detail: Optional[str] = None
    highlight: bool = False


class CardView(BaseModel):
    """A card in the UI. Every value comes straight from server data."""
    name: str
    alias: Optional[str] = None
    badge: Optional[str] = None
    metrics: list[Metric] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)   # short labels, e.g. "Free to join"


class Meter(BaseModel):
    """Eligibility bar: the user's income vs the card's minimum (both from the verdict)."""
    title: str
    you: str
    needed: str
    status: str
    meets: bool
    fill: float                      # 0..1, share of the minimum the user's income covers


class ChatReply(BaseModel):
    reply: str
    request_id: str
    intent: Intent
    cards: list[CardView] = Field(default_factory=list)
    note: Optional[str] = None
    warning: Optional[str] = None      # shown when the card data looks wrong
    meter: Optional[Meter] = None
    mode: Optional[str] = None         # recommend / card_details / compare / eligibility_*
    refused: bool = False
    clarifying: bool = False
    fallback_table: bool = False
    suspect_data: bool = False