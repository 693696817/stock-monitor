import json
import os
import re
from openai import OpenAI
from app.config import Config

class AIAnalysisService:
    def __init__(self):
        self.model = Config.get_ai_model_id()  # 从配置获取 model ID
        self.client = OpenAI(
            api_key = Config.get_ai_api_key(),  # 从配置获取 API Key
            base_url = "https://ark.cn-beijing.volces.com/api/v3"
        )
        
    def analyze_value_investment(self, analysis_data):
        """
        对股票进行价值投资分析
        :param analysis_data: 包含各项财务指标的字典
        :return: AI分析结果
        """
        try:
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
                
                # 构建完整的返回结果
                result = analysis_result
                
                print(f"最终返回结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                return result
                
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {str(e)}")
                # 如果JSON解析失败，返回错误信息
                return {
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
            
        except Exception as e:
            print(f"AI分析失败: {str(e)}")
            print(f"错误详情: {e.__class__.__name__}")
            import traceback
            print(f"错误堆栈: {traceback.format_exc()}")
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
2. 存货周转率为0可能表示数据缺失，分析时需要谨慎对待
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

请确保返回的是一个有效的JSON格式，数值使用数字而不是字符串（价格、市值等），文本分析使用字符串。分析要客观、专业、详细。"""

        # 组合完整的提示词
        prompt = data_section + analysis_requirements
        
        return prompt 