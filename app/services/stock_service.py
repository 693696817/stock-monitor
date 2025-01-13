import json
import os
from datetime import datetime
import pandas as pd
from app import pro
from app.config import Config
import numpy as np

class StockService:
    def __init__(self):
        self.watchlist = {}
        self.cache_file = os.path.join(Config.BASE_DIR, "stock_cache.json")
        self.load_watchlist()
        self.load_cache()

    def load_watchlist(self):
        try:
            if os.path.exists(Config.CONFIG_FILE):
                with open(Config.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.watchlist = data.get('watchlist', {})
        except Exception as e:
            print(f"Error loading watchlist: {str(e)}")
            self.watchlist = {}

    def _save_watchlist(self):
        try:
            with open(Config.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'watchlist': self.watchlist}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving watchlist: {str(e)}")

    def load_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache_data = json.load(f)
            else:
                self.cache_data = {}
        except Exception as e:
            print(f"Error loading cache: {str(e)}")
            self.cache_data = {}

    def save_cache(self, stock_code, data):
        try:
            self.cache_data[stock_code] = {
                'data': data,
                'timestamp': datetime.now().strftime('%Y-%m-%d')
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error saving cache: {str(e)}")

    def get_stock_info(self, stock_code: str, force_refresh: bool = False):
        try:
            # 检查缓存
            today = datetime.now().strftime('%Y-%m-%d')
            if not force_refresh and stock_code in self.cache_data and self.cache_data[stock_code]['timestamp'] == today:
                print(f"从缓存获取股票 {stock_code} 的数据")
                cached_data = self.cache_data[stock_code]['data']
                cached_data['stock_info']['from_cache'] = True
                return cached_data

            # 如果强制刷新或缓存不存在或已过期，从API获取数据
            print(f"从API获取股票 {stock_code} 的数据...")

            # 处理股票代码格式
            if len(stock_code) != 6:
                return {"error": "股票代码格式错误"}
                
            # 确定交易所
            if stock_code.startswith('6'):
                ts_code = f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                ts_code = f"{stock_code}.SZ"
            else:
                return {"error": "不支持的股票代码"}

            # 获取基本信息和总市值
            basic_info = pro.daily_basic(ts_code=ts_code, fields='ts_code,total_mv', limit=1)
            if basic_info.empty:
                return {"error": "股票代码不存在"}

            # 获取股票名称
            stock_name = pro.stock_basic(ts_code=ts_code, fields='name').iloc[0]['name']

            # 获取最新财务指标
            fina_indicator = pro.fina_indicator(ts_code=ts_code, period=datetime.now().strftime('%Y%m%d'), fields='roe,grossprofit_margin,netprofit_margin,debt_to_assets,op_income_yoy,netprofit_yoy,bps,ocfps')
            if fina_indicator.empty:
                fina_indicator = pro.fina_indicator(ts_code=ts_code, limit=1)
                
            # 获取实时行情
            today = datetime.now().strftime('%Y%m%d')
            daily_data = pro.daily(ts_code=basic_info['ts_code'].iloc[0], start_date=today, end_date=today)
            if daily_data.empty:
                daily_data = pro.daily(ts_code=basic_info['ts_code'].iloc[0], limit=1)
                if daily_data.empty:
                    return {"error": "无法获取股票行情数据"}

            # 获取市值信息（用于其他指标）
            daily_basic = pro.daily_basic(ts_code=basic_info['ts_code'].iloc[0], 
                                        fields='ts_code,trade_date,pe,pb,ps,dv_ratio',
                                        limit=1)
            
            if daily_basic.empty:
                return {"error": "无法获取股票基础数据"}
                
            latest_basic = daily_basic.iloc[0]
            latest_fina = fina_indicator.iloc[0] if not fina_indicator.empty else pd.Series()
            
            # 计算实时总市值（单位：亿元）
            current_price = float(daily_data['close'].iloc[0])
            market_value = float(basic_info['total_mv'].iloc[0]) / 10000  # 转换为亿元
            print(f"市值计算: 当前价格={current_price}, 总市值={market_value}亿元")
            
            # 处理股息率：tushare返回的是百分比值，需要转换为小数
            dv_ratio = float(latest_basic['dv_ratio']) if pd.notna(latest_basic['dv_ratio']) else 0
            dividend_yield = round(dv_ratio / 100, 4)  # 转换为小数
            
            # 处理财务指标，确保所有值都有默认值0，转换为小数
            roe = round(float(latest_fina['roe']) / 100, 4) if pd.notna(latest_fina.get('roe')) else 0
            gross_profit_margin = round(float(latest_fina['grossprofit_margin']) / 100, 4) if pd.notna(latest_fina.get('grossprofit_margin')) else 0
            net_profit_margin = round(float(latest_fina['netprofit_margin']) / 100, 4) if pd.notna(latest_fina.get('netprofit_margin')) else 0
            debt_to_assets = round(float(latest_fina['debt_to_assets']) / 100, 4) if pd.notna(latest_fina.get('debt_to_assets')) else 0
            revenue_yoy = round(float(latest_fina['op_income_yoy']) / 100, 4) if pd.notna(latest_fina.get('op_income_yoy')) else 0
            net_profit_yoy = round(float(latest_fina['netprofit_yoy']) / 100, 4) if pd.notna(latest_fina.get('netprofit_yoy')) else 0
            bps = round(float(latest_fina['bps']), 3) if pd.notna(latest_fina.get('bps')) else 0  # 保留3位小数
            ocfps = round(float(latest_fina['ocfps']), 3) if pd.notna(latest_fina.get('ocfps')) else 0  # 保留3位小数
            
            stock_info = {
                "code": stock_code,
                "name": stock_name,
                "market_value": round(market_value, 2),  # 总市值（亿元）
                "pe_ratio": round(float(latest_basic['pe']), 2) if pd.notna(latest_basic['pe']) else 0,  # 市盈率
                "pb_ratio": round(float(latest_basic['pb']), 2) if pd.notna(latest_basic['pb']) else 0,  # 市净率
                "ps_ratio": round(float(latest_basic['ps']), 2) if pd.notna(latest_basic['ps']) else 0,  # 市销率
                "dividend_yield": dividend_yield,  # 股息率（小数）
                "price": round(current_price, 2),  # 股价保留2位小数
                "change_percent": round(float(daily_data['pct_chg'].iloc[0]) / 100, 4),  # 涨跌幅转换为小数
                # 财务指标（全部转换为小数）
                "roe": roe,  # ROE（小数）
                "gross_profit_margin": gross_profit_margin,  # 毛利率（小数）
                "net_profit_margin": net_profit_margin,  # 净利率（小数）
                "debt_to_assets": debt_to_assets,  # 资产负债率（小数）
                "revenue_yoy": revenue_yoy,  # 营收增长率（小数）
                "net_profit_yoy": net_profit_yoy,  # 净利润增长率（小数）
                "bps": bps,  # 每股净资产
                "ocfps": ocfps,  # 每股经营现金流
                "from_cache": False
            }

            # 获取目标值
            targets = self.watchlist.get(stock_code, {})

            result = {
                "stock_info": stock_info,
                "targets": targets
            }

            # 保存到缓存
            self.save_cache(stock_code, result)

            return result
        except Exception as e:
            print(f"Error fetching stock info: {str(e)}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return {"error": f"获取股票数据失败: {str(e)}"}

    def get_watchlist(self):
        result = []
        for stock_code, targets in self.watchlist.items():
            try:
                # 从缓存获取数据
                today = datetime.now().strftime('%Y-%m-%d')
                if stock_code in self.cache_data and self.cache_data[stock_code]['timestamp'] == today:
                    result.append(self.cache_data[stock_code]['data'])
                    continue

                # 如果没有缓存，只获取基本信息
                if stock_code.startswith('6'):
                    ts_code = f"{stock_code}.SH"
                elif stock_code.startswith(('0', '3')):
                    ts_code = f"{stock_code}.SZ"
                else:
                    print(f"不支持的股票代码: {stock_code}")
                    continue
                    
                # 获取股票名称
                stock_name = pro.stock_basic(ts_code=ts_code, fields='name').iloc[0]['name']
                
                result.append({
                    "stock_info": {
                        "code": stock_code,
                        "name": stock_name
                    },
                    "targets": targets
                })
            except Exception as e:
                print(f"Error getting watchlist info for {stock_code}: {str(e)}")
                continue
        return result

    def add_watch(self, stock_code: str, target_market_value_min: float = None, target_market_value_max: float = None):
        self.watchlist[stock_code] = {
            "target_market_value": {
                "min": target_market_value_min,
                "max": target_market_value_max
            }
        }
        self._save_watchlist()
        return {"status": "success"}

    def remove_watch(self, stock_code: str):
        if stock_code in self.watchlist:
            del self.watchlist[stock_code]
            # 同时删除缓存
            if stock_code in self.cache_data:
                del self.cache_data[stock_code]
                try:
                    with open(self.cache_file, 'w', encoding='utf-8') as f:
                        json.dump(self.cache_data, f, ensure_ascii=False, indent=4)
                except Exception as e:
                    print(f"Error saving cache after removal: {str(e)}")
        self._save_watchlist()
        return {"status": "success"}

    def get_index_info(self):
        """获取主要指数数据"""
        try:
            # 主要指数代码列表
            index_codes = {
                '000001.SH': '上证指数',
                '399001.SZ': '深证成指',
                '399006.SZ': '创业板指',
                '000016.SH': '上证50',
                '000300.SH': '沪深300',
                '000905.SH': '中证500',
                '000852.SH': '中证1000',
                '899050.BJ': '北证50',
            }
            
            result = []
            for ts_code, name in index_codes.items():
                try:
                    # 获取指数基本信息
                    df = pro.index_daily(ts_code=ts_code, limit=1)
                    if not df.empty:
                        data = df.iloc[0]
                        # 获取K线数据(最近20天)
                        kline_df = pro.index_daily(ts_code=ts_code, limit=20)
                        kline_data = []
                        if not kline_df.empty:
                            for _, row in kline_df.iterrows():
                                kline_data.append({
                                    'date': row['trade_date'],
                                    'open': float(row['open']),
                                    'close': float(row['close']),
                                    'high': float(row['high']),
                                    'low': float(row['low']),
                                    'vol': float(row['vol'])
                                })
                        
                        result.append({
                            'code': ts_code,
                            'name': name,
                            'price': float(data['close']),
                            'change': float(data['pct_chg']),
                            'kline_data': kline_data
                        })
                except Exception as e:
                    print(f"获取指数 {ts_code} 数据失败: {str(e)}")
                    continue
            
            return result
        except Exception as e:
            print(f"获取指数数据失败: {str(e)}")
            return [] 

    def get_company_detail(self, stock_code: str):
        try:
            print(f"开始获取公司详情: {stock_code}")
            
            # 处理股票代码格式
            if stock_code.startswith('6'):
                ts_code = f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                ts_code = f"{stock_code}.SZ"
            else:
                print(f"不支持的股票代码格式: {stock_code}")
                return {"error": "不支持的股票代码"}

            print(f"转换后的ts_code: {ts_code}")

            # 获取公司基本信息
            basic = pro.stock_basic(ts_code=ts_code, fields='name,industry,area,list_date')
            if basic.empty:
                print(f"无法获取公司基本信息: {ts_code}")
                return {"error": "无法获取公司信息"}
            
            company_info = basic.iloc[0]
            print(f"获取到的公司基本信息: {company_info.to_dict()}")
            
            # 获取公司详细信息
            try:
                company_detail = pro.stock_company(ts_code=ts_code)
                if not company_detail.empty:
                    detail_info = company_detail.iloc[0]
                    company_detail_dict = {
                        "com_name": str(detail_info.get('com_name', '')),
                        "chairman": str(detail_info.get('chairman', '')),
                        "manager": str(detail_info.get('manager', '')),
                        "secretary": str(detail_info.get('secretary', '')),
                        "reg_capital": float(detail_info.get('reg_capital', 0)) if pd.notna(detail_info.get('reg_capital')) else 0,
                        "setup_date": str(detail_info.get('setup_date', '')),
                        "province": str(detail_info.get('province', '')),
                        "city": str(detail_info.get('city', '')),
                        "introduction": str(detail_info.get('introduction', '')),
                        "website": f"http://{str(detail_info.get('website', '')).strip('http://').strip('https://')}" if detail_info.get('website') else "",
                        "email": str(detail_info.get('email', '')),
                        "office": str(detail_info.get('office', '')),
                        "employees": int(detail_info.get('employees', 0)) if pd.notna(detail_info.get('employees')) else 0,
                        "main_business": str(detail_info.get('main_business', '')),
                        "business_scope": str(detail_info.get('business_scope', ''))
                    }
                else:
                    company_detail_dict = {
                        "com_name": "", "chairman": "", "manager": "", "secretary": "",
                        "reg_capital": 0, "setup_date": "", "province": "", "city": "",
                        "introduction": "", "website": "", "email": "", "office": "",
                        "employees": 0, "main_business": "", "business_scope": ""
                    }
            except Exception as e:
                print(f"获取公司详细信息失败: {str(e)}")
                company_detail_dict = {
                    "com_name": "", "chairman": "", "manager": "", "secretary": "",
                    "reg_capital": 0, "setup_date": "", "province": "", "city": "",
                    "introduction": "", "website": "", "email": "", "office": "",
                    "employees": 0, "main_business": "", "business_scope": ""
                }
            
            # 获取最新财务指标
            try:
                fina = pro.fina_indicator(ts_code=ts_code, period=datetime.now().strftime('%Y%m%d'))
                if fina.empty:
                    print("当前期间无财务数据，尝试获取最新一期数据")
                    fina = pro.fina_indicator(ts_code=ts_code, limit=1)
                
                if fina.empty:
                    print(f"无法获取财务指标数据: {ts_code}")
                    return {"error": "无法获取财务数据"}
                    
                fina_info = fina.iloc[0]
                print(f"获取到的财务指标: {fina_info.to_dict()}")
            except Exception as e:
                print(f"获取财务指标失败: {str(e)}")
                return {"error": "获取财务指标失败"}
            
            # 获取市值信息（用于PE、PB等指标）
            try:
                daily_basic = pro.daily_basic(ts_code=ts_code, fields='pe,pb,ps,dv_ratio', limit=1)
                if not daily_basic.empty:
                    latest_basic = daily_basic.iloc[0]
                else:
                    print("无法获取PE/PB数据")
                    latest_basic = pd.Series({'pe': 0, 'pb': 0, 'ps': 0, 'dv_ratio': 0})
            except Exception as e:
                print(f"获取PE/PB失败: {str(e)}")
                latest_basic = pd.Series({'pe': 0, 'pb': 0, 'ps': 0, 'dv_ratio': 0})
            
            result = {
                "basic_info": {
                    "name": str(company_info['name']),
                    "industry": str(company_info['industry']),
                    "list_date": str(company_info['list_date']),
                    "area": str(company_info['area']),
                    **company_detail_dict
                },
                "financial_info": {
                    # 估值指标
                    "pe_ratio": float(latest_basic['pe']) if pd.notna(latest_basic['pe']) else 0,
                    "pb_ratio": float(latest_basic['pb']) if pd.notna(latest_basic['pb']) else 0,
                    "ps_ratio": float(latest_basic['ps']) if pd.notna(latest_basic['ps']) else 0,
                    "dividend_yield": float(latest_basic['dv_ratio'])/100 if pd.notna(latest_basic['dv_ratio']) else 0,
                    
                    # 盈利能力
                    "roe": float(fina_info['roe']) if pd.notna(fina_info.get('roe')) else 0,
                    "roe_dt": float(fina_info['roe_dt']) if pd.notna(fina_info.get('roe_dt')) else 0,
                    "roa": float(fina_info['roa']) if pd.notna(fina_info.get('roa')) else 0,
                    "grossprofit_margin": float(fina_info['grossprofit_margin']) if pd.notna(fina_info.get('grossprofit_margin')) else 0,
                    "netprofit_margin": float(fina_info['netprofit_margin']) if pd.notna(fina_info.get('netprofit_margin')) else 0,
                    
                    # 成长能力
                    "netprofit_yoy": float(fina_info['netprofit_yoy']) if pd.notna(fina_info.get('netprofit_yoy')) else 0,
                    "dt_netprofit_yoy": float(fina_info['dt_netprofit_yoy']) if pd.notna(fina_info.get('dt_netprofit_yoy')) else 0,
                    "tr_yoy": float(fina_info['tr_yoy']) if pd.notna(fina_info.get('tr_yoy')) else 0,
                    "or_yoy": float(fina_info['or_yoy']) if pd.notna(fina_info.get('or_yoy')) else 0,
                    
                    # 营运能力
                    "assets_turn": float(fina_info['assets_turn']) if pd.notna(fina_info.get('assets_turn')) else 0,
                    "inv_turn": float(fina_info['inv_turn']) if pd.notna(fina_info.get('inv_turn')) else 0,
                    "ar_turn": float(fina_info['ar_turn']) if pd.notna(fina_info.get('ar_turn')) else 0,
                    "ca_turn": float(fina_info['ca_turn']) if pd.notna(fina_info.get('ca_turn')) else 0,
                    
                    # 偿债能力
                    "current_ratio": float(fina_info['current_ratio']) if pd.notna(fina_info.get('current_ratio')) else 0,
                    "quick_ratio": float(fina_info['quick_ratio']) if pd.notna(fina_info.get('quick_ratio')) else 0,
                    "debt_to_assets": float(fina_info['debt_to_assets']) if pd.notna(fina_info.get('debt_to_assets')) else 0,
                    "debt_to_eqt": float(fina_info['debt_to_eqt']) if pd.notna(fina_info.get('debt_to_eqt')) else 0,
                    
                    # 现金流
                    "ocf_to_or": float(fina_info['ocf_to_or']) if pd.notna(fina_info.get('ocf_to_or')) else 0,
                    "ocf_to_opincome": float(fina_info['ocf_to_opincome']) if pd.notna(fina_info.get('ocf_to_opincome')) else 0,
                    "ocf_yoy": float(fina_info['ocf_yoy']) if pd.notna(fina_info.get('ocf_yoy')) else 0,
                    
                    # 每股指标
                    "eps": float(fina_info['eps']) if pd.notna(fina_info.get('eps')) else 0,
                    "dt_eps": float(fina_info['dt_eps']) if pd.notna(fina_info.get('dt_eps')) else 0,
                    "bps": float(fina_info['bps']) if pd.notna(fina_info.get('bps')) else 0,
                    "ocfps": float(fina_info['ocfps']) if pd.notna(fina_info.get('ocfps')) else 0,
                    "retainedps": float(fina_info['retainedps']) if pd.notna(fina_info.get('retainedps')) else 0,
                    "cfps": float(fina_info['cfps']) if pd.notna(fina_info.get('cfps')) else 0,
                    "ebit_ps": float(fina_info['ebit_ps']) if pd.notna(fina_info.get('ebit_ps')) else 0,
                    "fcff_ps": float(fina_info['fcff_ps']) if pd.notna(fina_info.get('fcff_ps')) else 0,
                    "fcfe_ps": float(fina_info['fcfe_ps']) if pd.notna(fina_info.get('fcfe_ps')) else 0
                }
            }
            
            print(f"返回结果: {result}")
            return result
            
        except Exception as e:
            print(f"Error getting company detail: {str(e)}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return {"error": f"获取公司详情失败: {str(e)}"} 

    def get_top_holders(self, stock_code: str):
        """获取前十大股东数据"""
        try:
            # 处理股票代码格式
            if stock_code.startswith('6'):
                ts_code = f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                ts_code = f"{stock_code}.SZ"
            else:
                return {"error": "不支持的股票代码"}

            # 获取最新一期的股东数据
            df = pro.top10_holders(ts_code=ts_code, limit=10)
            if df.empty:
                return {"error": "暂无股东数据"}

            # 按持股比例降序排序
            df = df.sort_values('hold_ratio', ascending=False)
            
            # 获取最新的报告期
            latest_end_date = df['end_date'].max()
            latest_data = df[df['end_date'] == latest_end_date]

            holders = []
            for _, row in latest_data.iterrows():
                holders.append({
                    "holder_name": str(row['holder_name']),
                    "hold_amount": float(row['hold_amount']) if pd.notna(row['hold_amount']) else 0,
                    "hold_ratio": float(row['hold_ratio']) if pd.notna(row['hold_ratio']) else 0,
                    "hold_change": float(row['hold_change']) if pd.notna(row['hold_change']) else 0,
                    "ann_date": str(row['ann_date']),
                    "end_date": str(row['end_date'])
                })

            result = {
                "holders": holders,
                "total_ratio": sum(holder['hold_ratio'] for holder in holders),  # 合计持股比例
                "report_date": str(latest_end_date)  # 报告期
            }
            
            return result
            
        except Exception as e:
            print(f"获取股东数据失败: {str(e)}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return {"error": f"获取股东数据失败: {str(e)}"} 

    def get_value_analysis_data(self, stock_code: str):
        """获取价值投资分析所需的关键财务指标"""
        try:
            # 处理股票代码格式
            if stock_code.startswith('6'):
                ts_code = f"{stock_code}.SH"
            elif stock_code.startswith(('0', '3')):
                ts_code = f"{stock_code}.SZ"
            else:
                return {"error": "不支持的股票代码"}

            # 获取最新每日指标（估值数据）
            daily_basic = pro.daily_basic(ts_code=ts_code, fields='pe,pb,ps,dv_ratio,total_mv', limit=1)
            if daily_basic.empty:
                return {"error": "无法获取股票估值数据"}

            # 获取最新财务指标
            fina = pro.fina_indicator(ts_code=ts_code, fields='''roe,grossprofit_margin,netprofit_margin,
                netprofit_yoy,dt_netprofit_yoy,tr_yoy,or_yoy,assets_turn,inv_turn,ar_turn,current_ratio,
                quick_ratio,debt_to_assets,ocf_to_or,ocf_yoy,eps,bps,cfps,ocfps,retainedps''', limit=1)
            if fina.empty:
                return {"error": "无法获取财务指标数据"}

            # 获取股票名称和当前价格
            basic_info = pro.daily(ts_code=ts_code, fields='close,trade_date', limit=1)
            stock_name = pro.stock_basic(ts_code=ts_code, fields='name').iloc[0]['name']

            # 整合数据
            latest_daily = daily_basic.iloc[0]
            latest_fina = fina.iloc[0]
            latest_price = basic_info.iloc[0]

            analysis_data = {
                "stock_info": {
                    "code": stock_code,
                    "name": stock_name,
                    "current_price": float(latest_price['close']),
                    "trade_date": str(latest_price['trade_date'])
                },
                "valuation": {
                    "pe_ratio": float(latest_daily['pe']) if pd.notna(latest_daily['pe']) else None,
                    "pb_ratio": float(latest_daily['pb']) if pd.notna(latest_daily['pb']) else None,
                    "ps_ratio": float(latest_daily['ps']) if pd.notna(latest_daily['ps']) else None,
                    "dividend_yield": float(latest_daily['dv_ratio'])/100 if pd.notna(latest_daily['dv_ratio']) else None,
                    "total_market_value": float(latest_daily['total_mv'])/10000 if pd.notna(latest_daily['total_mv']) else None  # 转换为亿元
                },
                "profitability": {
                    "roe": float(latest_fina['roe'])/100 if pd.notna(latest_fina['roe']) else None,
                    "gross_margin": float(latest_fina['grossprofit_margin'])/100 if pd.notna(latest_fina['grossprofit_margin']) else None,
                    "net_margin": float(latest_fina['netprofit_margin'])/100 if pd.notna(latest_fina['netprofit_margin']) else None
                },
                "growth": {
                    "net_profit_growth": float(latest_fina['netprofit_yoy'])/100 if pd.notna(latest_fina['netprofit_yoy']) else None,
                    "deducted_net_profit_growth": float(latest_fina['dt_netprofit_yoy'])/100 if pd.notna(latest_fina['dt_netprofit_yoy']) else None,
                    "revenue_growth": float(latest_fina['tr_yoy'])/100 if pd.notna(latest_fina['tr_yoy']) else None,
                    "operating_revenue_growth": float(latest_fina['or_yoy'])/100 if pd.notna(latest_fina['or_yoy']) else None
                },
                "operation": {
                    "asset_turnover": float(latest_fina['assets_turn']) if pd.notna(latest_fina['assets_turn']) else None,
                    "inventory_turnover": float(latest_fina['inv_turn']) if pd.notna(latest_fina['inv_turn']) else None,
                    "receivables_turnover": float(latest_fina['ar_turn']) if pd.notna(latest_fina['ar_turn']) else None
                },
                "solvency": {
                    "current_ratio": float(latest_fina['current_ratio']) if pd.notna(latest_fina['current_ratio']) else None,
                    "quick_ratio": float(latest_fina['quick_ratio']) if pd.notna(latest_fina['quick_ratio']) else None,
                    "debt_to_assets": float(latest_fina['debt_to_assets'])/100 if pd.notna(latest_fina['debt_to_assets']) else None
                },
                "cash_flow": {
                    "ocf_to_revenue": float(latest_fina['ocf_to_or'])/100 if pd.notna(latest_fina['ocf_to_or']) else None,
                    "ocf_growth": float(latest_fina['ocf_yoy'])/100 if pd.notna(latest_fina['ocf_yoy']) else None
                },
                "per_share": {
                    "eps": float(latest_fina['eps']) if pd.notna(latest_fina['eps']) else None,
                    "bps": float(latest_fina['bps']) if pd.notna(latest_fina['bps']) else None,
                    "cfps": float(latest_fina['cfps']) if pd.notna(latest_fina['cfps']) else None,
                    "ocfps": float(latest_fina['ocfps']) if pd.notna(latest_fina['ocfps']) else None,
                    "retained_eps": float(latest_fina['retainedps']) if pd.notna(latest_fina['retainedps']) else None
                }
            }

            return analysis_data

        except Exception as e:
            print(f"获取价值投资分析数据失败: {str(e)}")
            import traceback
            print(f"详细错误: {traceback.format_exc()}")
            return {"error": f"获取价值投资分析数据失败: {str(e)}"} 