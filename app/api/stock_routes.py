from fastapi import APIRouter, Request, Form
from typing import Optional
from app.services.stock_service import StockService
from app.services.ai_analysis_service import AIAnalysisService
from app import templates

router = APIRouter(prefix="")
stock_service = StockService()
ai_service = AIAnalysisService()

@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/api/stock_info/{stock_code}")
async def get_stock_info(stock_code: str, force_refresh: bool = False):
    return stock_service.get_stock_info(stock_code, force_refresh)

@router.get("/api/watchlist")
async def get_watchlist():
    return stock_service.get_watchlist()

@router.post("/api/add_watch")
async def add_watch(
    stock_code: str = Form(...),
    target_market_value_min: Optional[float] = Form(None),
    target_market_value_max: Optional[float] = Form(None)
):
    return stock_service.add_watch(stock_code, target_market_value_min, target_market_value_max)

@router.delete("/api/remove_watch/{stock_code}")
async def remove_watch(stock_code: str):
    return stock_service.remove_watch(stock_code)

@router.get("/api/index_info")
async def get_index_info():
    return stock_service.get_index_info()

@router.get("/market")
async def market(request: Request):
    return templates.TemplateResponse("market.html", {"request": request})

@router.get("/api/company_detail/{stock_code}")
async def get_company_detail(stock_code: str):
    return stock_service.get_company_detail(stock_code)

@router.get("/api/holders/{stock_code}")
async def get_top_holders(stock_code: str):
    """获取前十大股东数据"""
    return stock_service.get_top_holders(stock_code)

@router.get("/api/performance_forecast/{stock_code}")
async def get_performance_forecast(stock_code: str):
    """获取业绩预告数据"""
    # 处理股票代码格式
    if stock_code.startswith('6'):
        ts_code = f"{stock_code}.SH"
    elif stock_code.startswith(('0', '3')):
        ts_code = f"{stock_code}.SZ"
    else:
        return {"error": "不支持的股票代码"}
        
    return stock_service.get_forecast_data(ts_code)

@router.get("/api/value_analysis/{stock_code}")
async def get_value_analysis(stock_code: str):
    """获取价值投资分析数据"""
    return stock_service.get_value_analysis_data(stock_code)

@router.get("/api/ai_analysis/{stock_code}")
async def get_ai_analysis(stock_code: str, force_refresh: bool = False):
    """获取AI价值投资分析结果"""
    try:
        # 首先获取价值分析数据
        analysis_data = stock_service.get_value_analysis_data(stock_code)
        if "error" in analysis_data:
            return analysis_data
            
        # 使用AI服务进行分析
        return ai_service.analyze_value_investment(analysis_data, force_refresh)
    except Exception as e:
        return {"error": f"AI分析失败: {str(e)}"}

@router.post("/api/update_target")
async def update_target(
    stock_code: str = Form(...),
    target_market_value_min: Optional[float] = Form(None),
    target_market_value_max: Optional[float] = Form(None)
):
    """更新股票的目标市值"""
    return stock_service.update_target(stock_code, target_market_value_min, target_market_value_max)

@router.get("/api/tao_analysis/{stock_code}")
async def get_tao_analysis(stock_code: str):
    """获取基于道德经的公司分析"""
    try:
        # 首先获取公司详细信息
        company_info = stock_service.get_company_detail(stock_code)
        if "error" in company_info:
            return company_info
            
        # 使用AI服务进行道德经分析
        return ai_service.analyze_tao_philosophy(company_info)
    except Exception as e:
        return {"error": f"道德经分析失败: {str(e)}"}

@router.get("/api/master_analysis/{stock_code}")
async def get_master_analysis(stock_code: str):
    """获取价值投资大咖的分析结果"""
    try:
        # 首先获取公司详细信息和财务数据
        company_info = stock_service.get_company_detail(stock_code)
        if "error" in company_info:
            return company_info
            
        value_analysis = stock_service.get_value_analysis_data(stock_code)
        if "error" in value_analysis:
            return value_analysis
            
        # 使用AI服务进行大咖分析
        return ai_service.analyze_by_masters(company_info, value_analysis)
    except Exception as e:
        return {"error": f"价值投资大咖分析失败: {str(e)}"} 