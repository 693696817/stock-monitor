import json
import os
from openai import OpenAI
from app.config import Config

class AIAnalysisService:
    def __init__(self):
        # 配置OpenAI客户端连接到Volces API
        self.model = os.getenv('VOLCES_MODEL_ID', 'your_model_id_here')  # 从环境变量获取
        self.client = OpenAI(
            api_key = os.getenv('VOLCES_API_KEY', 'your_api_key_here'),  # 从环境变量获取
            base_url = os.getenv('VOLCES_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
        )
        # 创建AI分析结果缓存目录
        self.cache_dir = os.path.join(Config.BASE_DIR, "ai_stock_analysis")
        self.dao_cache_dir = os.path.join(Config.BASE_DIR, "dao_analysis")
        self.daka_cache_dir = os.path.join(Config.BASE_DIR, "daka_analysis")
        
        # 确保所有缓存目录存在
        for directory in [self.cache_dir, self.dao_cache_dir, self.daka_cache_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory)

    def get_cache_path(self, stock_code: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{stock_code}.json")

    def get_dao_cache_path(self, stock_code: str) -> str:
        """获取道德经分析缓存文件路径"""
        return os.path.join(self.dao_cache_dir, f"{stock_code}.json")

    def get_daka_cache_path(self, stock_code: str) -> str:
        """获取大咖分析缓存文件路径"""
        return os.path.join(self.daka_cache_dir, f"{stock_code}.json")

    def load_cache(self, stock_code: str):
        """加载缓存的AI分析结果"""
        cache_path = self.get_cache_path(stock_code)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取AI分析缓存失败: {str(e)}")
        return None

    def save_cache(self, stock_code: str, analysis_result: dict):
        """保存AI分析结果到缓存"""
        cache_path = self.get_cache_path(stock_code)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(analysis_result, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存AI分析缓存失败: {str(e)}")

    def load_dao_cache(self, stock_code: str):
        """加载缓存的道德经分析结果"""
        cache_path = self.get_dao_cache_path(stock_code)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取道德经分析缓存失败: {str(e)}")
        return None

    def save_dao_cache(self, stock_code: str, analysis_result: dict):
        """保存道德经分析结果到缓存"""
        cache_path = self.get_dao_cache_path(stock_code)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(analysis_result, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存道德经分析缓存失败: {str(e)}")

    def load_daka_cache(self, stock_code: str):
        """加载缓存的大咖分析结果"""
        cache_path = self.get_daka_cache_path(stock_code)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取大咖分析缓存失败: {str(e)}")
        return None

    def save_daka_cache(self, stock_code: str, analysis_result: dict):
        """保存大咖分析结果到缓存"""
        cache_path = self.get_daka_cache_path(stock_code)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(analysis_result, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存大咖分析缓存失败: {str(e)}")

    def analyze_value_investment(self, analysis_data: dict, force_refresh: bool = False):
        """
        对股票进行价值投资分析
        :param analysis_data: 包含各项财务指标的字典
        :param force_refresh: 是否强制刷新分析结果
        :return: AI分析结果
        """
        try:
            stock_code = analysis_data["stock_info"]["code"]
            
            # 如果不是强制刷新，尝试从缓存加载
            if not force_refresh:
                cached_result = self.load_cache(stock_code)
                if cached_result:
                    print(f"从缓存加载AI分析结果: {stock_code}")
                    return cached_result

            # 打印输入数据用于调试
            print(f"输入的分析数据: {json.dumps(analysis_data, ensure_ascii=False, indent=2)}")
            
            # 构建提示词
            prompt = self._build_analysis_prompt(analysis_data)
            
            # 打印提示词用于调试
            print(f"AI分析提示词: {prompt}")
            
            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            # 获取分析结果
            analysis_text = response.choices[0].message.content
            print(f"AI原始返回结果: {analysis_text}")
            
            try:
                # 尝试解析JSON
                analysis_result = json.loads(analysis_text)
                print(f"解析后的JSON结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                
                # 保存到缓存
                self.save_cache(stock_code, analysis_result)
                
                return analysis_result
                
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {str(e)}")
                # 如果JSON解析失败，返回错误信息
                error_result = {
                    'stock_info': analysis_data.get('stock_info', {}),
                    'valuation': analysis_data.get('valuation', {}),
                    'profitability': analysis_data.get('profitability', {}),
                    'growth': analysis_data.get('growth', {}),
                    'operation': analysis_data.get('operation', {}),
                    'solvency': analysis_data.get('solvency', {}),
                    'cash_flow': analysis_data.get('cash_flow', {}),
                    'per_share': analysis_data.get('per_share', {}),
                    'analysis_result': {
                        "error": "AI返回的结果不是有效的JSON格式",
                        "raw_text": analysis_text
                    }
                }
                return error_result
                
        except Exception as e:
            print(f"AI分析失败: {str(e)}")
            return {"error": f"AI分析失败: {str(e)}"}
    
    def _parse_analysis_result(self, analysis_text, current_price):
        """
        解析AI返回的分析文本，提取结构化信息
        """
        try:
            print(f"开始解析分析文本...")
            
            # 提取投资建议
            suggestion_pattern = r"投资建议[：:]([\s\S]*?)(?=\n\n|$)"
            suggestion_match = re.search(suggestion_pattern, analysis_text, re.MULTILINE | re.DOTALL)
            investment_suggestion = suggestion_match.group(1).strip() if suggestion_match else ""
            print(f"提取到的投资建议: {investment_suggestion}")
            
            # 提取合理价格区间
            price_pattern = r"合理股价区间[：:]\s*(\d+\.?\d*)\s*[元-]\s*(\d+\.?\d*)[元]"
            price_match = re.search(price_pattern, analysis_text)
            if price_match:
                price_min = float(price_match.group(1))
                price_max = float(price_match.group(2))
            else:
                price_min = current_price * 0.8
                price_max = current_price * 1.2
            print(f"提取到的价格区间: {price_min}-{price_max}")
            
            # 提取目标市值区间（单位：亿元）
            market_value_pattern = r"目标市值区间[：:]\s*(\d+\.?\d*)\s*[亿-]\s*(\d+\.?\d*)[亿]"
            market_value_match = re.search(market_value_pattern, analysis_text)
            if market_value_match:
                market_value_min = float(market_value_match.group(1))
                market_value_max = float(market_value_match.group(2))
            else:
                # 尝试从文本中提取计算得出的市值
                calc_pattern = r"最低市值[=≈约]*(\d+\.?\d*)[亿].*最高市值[=≈约]*(\d+\.?\d*)[亿]"
                calc_match = re.search(calc_pattern, analysis_text)
                if calc_match:
                    market_value_min = float(calc_match.group(1))
                    market_value_max = float(calc_match.group(2))
                else:
                    market_value_min = 0
                    market_value_max = 0
            print(f"提取到的市值区间: {market_value_min}-{market_value_max}")
            
            # 提取各个分析维度的内容
            analysis_patterns = {
                "valuation_analysis": r"估值分析([\s\S]*?)(?=###\s*财务状况分析|###\s*成长性分析|$)",
                "financial_health": r"财务状况分析([\s\S]*?)(?=###\s*成长性分析|###\s*风险评估|$)",
                "growth_potential": r"成长性分析([\s\S]*?)(?=###\s*风险评估|###\s*投资建议|$)",
                "risk_assessment": r"风险评估([\s\S]*?)(?=###\s*投资建议|$)"
            }
            
            analysis_results = {}
            for key, pattern in analysis_patterns.items():
                match = re.search(pattern, analysis_text, re.MULTILINE | re.DOTALL)
                content = match.group(1).strip() if match else ""
                # 移除markdown标记和多余的空白字符
                content = re.sub(r'[#\-*]', '', content).strip()
                analysis_results[key] = content
                print(f"提取到的{key}: {content[:100]}...")
            
            return {
                "investment_suggestion": investment_suggestion,
                "analysis": analysis_results,
                "price_analysis": {
                    "reasonable_price_range": {
                        "min": price_min,
                        "max": price_max
                    },
                    "target_market_value": {
                        "min": market_value_min,
                        "max": market_value_max
                    }
                }
            }
            
        except Exception as e:
            print(f"解析分析结果失败: {str(e)}")
            print(f"错误详情: {e.__class__.__name__}")
            import traceback
            print(f"错误堆栈: {traceback.format_exc()}")
            return {
                "investment_suggestion": "分析结果解析失败",
                "analysis": {
                    "valuation_analysis": "解析失败",
                    "financial_health": "解析失败",
                    "growth_potential": "解析失败",
                    "risk_assessment": "解析失败"
                },
                "price_analysis": {
                    "reasonable_price_range": {
                        "min": current_price * 0.8,
                        "max": current_price * 1.2
                    },
                    "target_market_value": {
                        "min": 0,
                        "max": 0
                    }
                }
            }
    
    def _build_analysis_prompt(self, data):
        """
        构建AI分析提示词
        """
        stock_info = data.get('stock_info', {})
        valuation = data.get('valuation', {})
        profitability = data.get('profitability', {})
        growth = data.get('growth', {})
        operation = data.get('operation', {})
        solvency = data.get('solvency', {})
        cash_flow = data.get('cash_flow', {})
        per_share = data.get('per_share', {})
        
        # 格式化数值，保留4位小数
        def format_number(value):
            try:
                if value is None:
                    return "0.0000"
                if isinstance(value, (int, float)):
                    if abs(value) < 0.0001:  # 对于非常小的数值
                        return "0.0000"
                    return f"{value:.4f}"
                if isinstance(value, str):
                    try:
                        value = float(value)
                        if abs(value) < 0.0001:
                            return "0.0000"
                        return f"{value:.4f}"
                    except:
                        pass
                return str(value)
            except:
                return "0.0000"
        
        # 格式化百分比，保留2位小数
        def format_percent(value):
            try:
                if value is None:
                    return "0.00%"
                if isinstance(value, (int, float)):
                    # 如果值已经是小数形式（如0.5代表50%），则乘以100
                    if abs(value) <= 1:
                        value = value * 100
                    return f"{value:.2f}%"
                if isinstance(value, str):
                    try:
                        value = float(value)
                        if abs(value) <= 1:
                            value = value * 100
                        return f"{value:.2f}%"
                    except:
                        pass
                return "0.00%"
            except:
                return "0.00%"

        # 构建数据部分
        data_section = f"""请作为一位专业的价值投资分析师，对{stock_info.get('name', '')}({stock_info.get('code', '')})进行深入的价值投资分析。

当前市场信息：
- 市盈率(PE)：{format_number(valuation.get('pe_ratio'))}
- 市净率(PB)：{format_number(valuation.get('pb_ratio'))}
- 市销率(PS)：{format_number(valuation.get('ps_ratio'))}
- 股息率：{format_percent(valuation.get('dividend_yield'))}
- 总市值(亿元)：{format_number(valuation.get('total_market_value'))}
- 当前股价：{format_number(stock_info.get('current_price'))}元

盈利能力指标：
- ROE：{format_percent(profitability.get('roe'))}
- 毛利率：{format_percent(profitability.get('gross_margin'))}
- 净利率：{format_percent(profitability.get('net_margin'))}

成长能力指标：
- 净利润增长率：{format_percent(growth.get('net_profit_growth'))}
- 扣非净利润增长率：{format_percent(growth.get('deducted_net_profit_growth'))}
- 营收增长率：{format_percent(growth.get('revenue_growth'))}

运营能力指标：
- 总资产周转率：{format_number(operation.get('asset_turnover'))}次/年
- 存货周转率：{format_number(operation.get('inventory_turnover'))}次/年
- 应收账款周转率：{format_number(operation.get('receivables_turnover'))}次/年

偿债能力指标：
- 流动比率：{format_number(solvency.get('current_ratio'))}
- 速动比率：{format_number(solvency.get('quick_ratio'))}
- 资产负债率：{format_percent(solvency.get('debt_to_assets'))}

现金流指标：
- 经营现金流/营收比：{format_percent(cash_flow.get('ocf_to_revenue'))}
- 经营现金流同比增长：{format_percent(cash_flow.get('ocf_growth'))}

每股指标：
- 每股收益(EPS)：{format_number(per_share.get('eps'))}元
- 每股净资产(BPS)：{format_number(per_share.get('bps'))}元
- 每股现金流(CFPS)：{format_number(per_share.get('cfps'))}元
- 每股经营现金流(OCFPS)：{format_number(per_share.get('ocfps'))}元
- 每股未分配利润：{format_number(per_share.get('retained_eps'))}元"""

        # 构建分析要求部分
        analysis_requirements = """
请基于以上数据，从价值投资的角度进行分析。请特别注意：
1. 结合行业特点、公司竞争力、成长性等因素，给出合理的估值区间
2. 某些数据可能缺失或异常，分析时需要谨慎对待，或者从东财choice获取
3. 考虑当前市场环境和行业整体估值水平

在给出估值区间时，请充分考虑：
1. 公司所处行业特点和竞争格局
2. 公司的竞争优势和市场地位
3. 当前的盈利能力和成长性
4. 财务健康状况和风险因素
5. 宏观经济环境和行业周期
6. 可比公司的估值水平

请以JSON格式返回分析结果，包含以下内容：
1. investment_suggestion: 投资建议，包含summary(总体建议)、action(具体操作建议)和key_points(关注重点)
2. analysis: 详细分析，包含估值分析、财务健康状况、成长潜力和风险评估
3. price_analysis: 价格分析，包含合理价格区间和目标市值区间
实例：
    "price_analysis": {
        "合理价格区间": [
            xxx,
            xxx
        ],
        "目标市值区间": [
            xxx,
            xxx
        ]

请确保返回的是一个有效的JSON格式，数值使用数字而不是字符串（价格、市值等），文本分析使用字符串。分析要客观、专业、详细。"""

        # 组合完整的提示词
        prompt = data_section + analysis_requirements
        
        return prompt 

    def analyze_tao_philosophy(self, company_info: dict, force_refresh: bool = False):
        """
        基于道德经理念分析公司
        :param company_info: 公司信息
        :param force_refresh: 是否强制刷新分析结果
        :return: AI分析结果
        """
        try:
            stock_code = company_info.get('basic_info', {}).get('code')
            
            # 如果不是强制刷新，尝试从缓存加载
            if not force_refresh and stock_code:
                cached_result = self.load_dao_cache(stock_code)
                if cached_result:
                    print(f"从缓存加载道德经分析结果: {stock_code}")
                    return cached_result
            
            # 构建提示词
            prompt = self._build_tao_analysis_prompt(company_info)
            
            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            # 获取分析结果
            analysis_text = response.choices[0].message.content
            
            try:
                # 解析JSON结果
                analysis_result = json.loads(analysis_text)
                
                # 保存到缓存
                if stock_code:
                    self.save_dao_cache(stock_code, analysis_result)
                
                return analysis_result
            except json.JSONDecodeError as e:
                print(f"道德经分析结果JSON解析失败: {str(e)}")
                return {"error": "分析结果格式错误"}
                
        except Exception as e:
            print(f"道德经分析失败: {str(e)}")
            return {"error": f"道德经分析失败: {str(e)}"}
    
    def _build_tao_analysis_prompt(self, company_info: dict):
        """
        构建道德经分析提示词
        """
        basic_info = company_info.get('basic_info', {})
        
        prompt = f"""请作为一位精通道德经的智者，运用道德经的智慧来分析{basic_info.get('name', '')}({basic_info.get('code', '')})这家公司。

公司基本信息：
- 公司名称：{basic_info.get('name', '')}
- 所属行业：{basic_info.get('industry', '')}
- 主营业务：{basic_info.get('main_business', '')}
- 经营范围：{basic_info.get('business_scope', '')}
- 公司简介：{basic_info.get('introduction', '')}

请从道德经的智慧角度，分析以下几个方面：

1. 道德经视角：
- 公司的经营理念是否符合"道法自然"的原则
- 企业的发展是否遵循"无为而治"的智慧
- 公司是否体现"上善若水"的品质
- 管理方式是否符合"柔弱胜刚强"的道理

2. 企业道德评估：
- 公司对待员工、客户、供应商的态度
- 企业的社会责任感和可持续发展理念
- 公司的价值观和企业文化
- 经营中的道德风险评估

3. 投资建议：
- 基于道德经智慧的投资建议
- 长期发展潜力分析
- 需要关注的风险点
- 持有建议

请以JSON格式返回分析结果，包含以下字段：
1. tao_philosophy: 道德经视角的分析
2. business_ethics: 企业道德评估
3. investment_advice: 投资建议

分析要客观、专业、深入，同时体现道德经的智慧。"""
        
        return prompt 

    def analyze_by_masters(self, company_info: dict, value_analysis: dict, force_refresh: bool = False):
        """
        基于各位价值投资大咖的理念分析公司
        :param company_info: 公司信息
        :param value_analysis: 价值分析数据
        :param force_refresh: 是否强制刷新分析结果
        :return: AI分析结果
        """
        try:
            stock_code = company_info.get('basic_info', {}).get('code')
            
            # 如果不是强制刷新，尝试从缓存加载
            if not force_refresh and stock_code:
                cached_result = self.load_daka_cache(stock_code)
                if cached_result:
                    print(f"从缓存加载大咖分析结果: {stock_code}")
                    return cached_result
            
            # 打印输入数据用于调试
            print(f"公司信息: {json.dumps(company_info, ensure_ascii=False, indent=2)}")
            print(f"价值分析数据: {json.dumps(value_analysis, ensure_ascii=False, indent=2)}")
            
            # 构建提示词
            prompt = self._build_masters_analysis_prompt(company_info, value_analysis)
            
            # 打印提示词用于调试
            print(f"大咖分析提示词: {prompt}")
            
            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            # 获取分析结果
            analysis_text = response.choices[0].message.content
            print(f"AI原始返回结果: {analysis_text}")
            
            try:
                # 解析JSON结果
                analysis_result = json.loads(analysis_text)
                print(f"解析后的JSON结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                
                # 保存到缓存
                if stock_code:
                    self.save_daka_cache(stock_code, analysis_result)
                
                return analysis_result
            except json.JSONDecodeError as e:
                print(f"大咖分析结果JSON解析失败: {str(e)}")
                return {"error": "分析结果格式错误"}
                
        except Exception as e:
            print(f"价值投资大咖分析失败: {str(e)}")
            return {"error": f"价值投资大咖分析失败: {str(e)}"}
    
    def _build_masters_analysis_prompt(self, company_info: dict, value_analysis: dict):
        """
        构建价值投资大咖分析提示词
        """
        basic_info = company_info.get('basic_info', {})
        
        # 从value_analysis中获取财务数据
        valuation = value_analysis.get('valuation', {})
        profitability = value_analysis.get('profitability', {})
        growth = value_analysis.get('growth', {})
        operation = value_analysis.get('operation', {})
        solvency = value_analysis.get('solvency', {})
        cash_flow = value_analysis.get('cash_flow', {})
        per_share = value_analysis.get('per_share', {})
        stock_info = value_analysis.get('stock_info', {})
        
        # 格式化百分比
        def format_percent(value):
            if value is None:
                return '-'
            try:
                if isinstance(value, str):
                    value = float(value)
                if abs(value) <= 1:
                    value = value * 100
                return f"{value:.2f}%"
            except:
                return '-'
            
        # 格式化数字
        def format_number(value):
            if value is None:
                return '-'
            try:
                if isinstance(value, str):
                    value = float(value)
                return f"{value:.4f}"
            except:
                return '-'
        
        prompt = f"""请分别以五位价值投资大咖的视角，分析{basic_info.get('name', '')}({basic_info.get('code', '')})这家公司。

公司基本信息：
- 公司名称：{basic_info.get('name', '')}
- 所属行业：{basic_info.get('industry', '')}
- 主营业务：{basic_info.get('main_business', '')}
- 经营范围：{basic_info.get('business_scope', '')}
- 公司简介：{basic_info.get('introduction', '')}
- 法人代表：{basic_info.get('chairman', '')}
- 总经理：{basic_info.get('manager', '')}
- 注册资本：{basic_info.get('reg_capital', '')}万元
- 员工人数：{basic_info.get('employees', '')}人
- 成立日期：{basic_info.get('setup_date', '')}
- 上市日期：{basic_info.get('list_date', '')}

当前市场信息：
- 当前股价：{format_number(stock_info.get('current_price'))}元
- 总市值：{format_number(valuation.get('total_market_value'))}亿元
- 流通市值：{format_number(valuation.get('circulating_market_value'))}亿元
- 流通比例：{format_percent(valuation.get('circulating_ratio'))}
- 换手率：{format_percent(stock_info.get('turnover_ratio'))}

估值指标：
- 市盈率(PE)：{format_number(valuation.get('pe_ratio'))}
- 市净率(PB)：{format_number(valuation.get('pb_ratio'))}
- 市销率(PS)：{format_number(valuation.get('ps_ratio'))}
- 股息率：{format_percent(valuation.get('dividend_yield'))}

盈利能力指标：
- ROE：{format_percent(profitability.get('roe'))}
- ROE(扣非)：{format_percent(profitability.get('deducted_roe'))}
- ROA：{format_percent(profitability.get('roa'))}
- 毛利率：{format_percent(profitability.get('gross_margin'))}
- 净利率：{format_percent(profitability.get('net_margin'))}

成长能力指标：
- 净利润增长率：{format_percent(growth.get('net_profit_growth'))}
- 扣非净利润增长率：{format_percent(growth.get('deducted_net_profit_growth'))}
- 营业总收入增长率：{format_percent(growth.get('revenue_growth'))}
- 营业收入增长率：{format_percent(growth.get('operating_revenue_growth'))}

运营能力指标：
- 总资产周转率：{format_number(operation.get('asset_turnover'))}
- 存货周转率：{format_number(operation.get('inventory_turnover'))}
- 应收账款周转率：{format_number(operation.get('receivables_turnover'))}
- 流动资产周转率：{format_number(operation.get('current_asset_turnover'))}

偿债能力指标：
- 流动比率：{format_number(solvency.get('current_ratio'))}
- 速动比率：{format_number(solvency.get('quick_ratio'))}
- 资产负债率：{format_percent(solvency.get('debt_to_assets'))}
- 产权比率：{format_number(solvency.get('equity_ratio'))}

现金流指标：
- 经营现金流/营收：{format_percent(cash_flow.get('ocf_to_revenue'))}
- 经营现金流/经营利润：{format_percent(cash_flow.get('ocf_to_operating_profit'))}
- 经营现金流同比增长：{format_percent(cash_flow.get('ocf_growth'))}

每股指标：
- 每股收益(EPS)：{format_number(per_share.get('eps'))}元
- 每股收益(扣非)：{format_number(per_share.get('deducted_eps'))}元
- 每股净资产：{format_number(per_share.get('bps'))}元
- 每股经营现金流：{format_number(per_share.get('ocfps'))}元
- 每股留存收益：{format_number(per_share.get('retained_eps'))}元
- 每股现金流量：{format_number(per_share.get('cfps'))}元
- 每股息税前利润：{format_number(per_share.get('ebit_ps'))}元

请分别从以下五位投资大师的视角进行分析：

1. 巴菲特视角：
- 是否具有护城河（品牌优势、规模效应、专利技术等）
- 管理层能力和诚信（从财务指标、现金流等反映的经营能力）
- 业务是否容易理解（商业模式的清晰度）
- 长期竞争优势（市场地位、核心竞争力）
- 是否是好生意（盈利能力、现金流状况）
- 以合理价格购买优秀企业的原则（估值分析）

2. 格雷厄姆视角：
- 安全边际分析（基于净资产、市盈率等）
- 内在价值计算（基于盈利能力和资产价值）
- 财务安全性（偿债能力、资产质量）
- 是否具有投资价值（基于定量分析）
- 基于定量分析的结论（综合财务指标评估）

3. 林园视角：
- 行业成长性（收入增长、利润增长）
- 公司治理结构（股权结构、管理层背景）
- 研发创新能力（技术优势、产品创新）
- 市场竞争格局（市场份额、竞争态势）
- 估值是否合理（相对估值和绝对估值）

4. 李大霄视角：
- 市场地位和品牌价值（行业地位、品牌影响力）
- 行业发展趋势（产业政策、市场空间）
- 政策影响分析（行业政策、监管环境）
- 投资时机把握（技术面和基本面）
- 投资建议（综合分析结论）

5. 段永平视角：
- 商业模式分析（盈利模式、竞争优势）
- 用户价值（产品力、客户粘性）
- 企业文化（管理理念、团队建设）
- 长期发展潜力（成长空间、持续经营能力）
- 是否值得长期持有（投资价值判断）

请以JSON格式返回分析结果，包含以下字段：
1. buffett_analysis: 巴菲特的分析观点
2. graham_analysis: 格雷厄姆的分析观点
3. lin_yuan_analysis: 林园的分析观点
4. li_daxiao_analysis: 李大霄的分析观点
5. duan_yongping_analysis: 段永平的分析观点

分析要客观、专业、深入，并体现每位投资大师的独特投资理念。请基于上述详细的财务数据进行分析（如果指标缺失或异常，请联网获取），尤其是定量指标的解读。"""
        
        return prompt 