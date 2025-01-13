from pydantic import BaseModel
from typing import Dict, Optional, Union, List

class MarketValueTarget(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None

class StockTarget(BaseModel):
    target_market_value: Optional[MarketValueTarget] = None

class StockInfo(BaseModel):
    code: str
    name: str
    market_value: float
    pe_ratio: float
    pb_ratio: float
    ps_ratio: float
    dividend_yield: float
    price: float
    change_percent: float
    roe: float
    gross_profit_margin: float
    net_profit_margin: float
    debt_to_assets: float
    revenue_yoy: float
    net_profit_yoy: float
    bps: float
    ocfps: float

class StockResponse(BaseModel):
    stock_info: StockInfo
    targets: StockTarget 