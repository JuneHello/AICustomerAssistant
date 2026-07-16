"""多场景Few-shot示例模板，为 Agent 的工具调用与回复话术提供基准示范"""

FEW_SHOT_EXAMPLES = [
    {
        "scenario": "未发货退款申请",
        "user_query": "我刚才下错单了，订单号是9821389421，我想退款。",
        "thought": "用户要求退款，并且提供了明确的订单号 9821389421。订单尚未发货，属于未发货退款场景。我需要核实订单信息。",
        "actions": [
            {"tool": "query_order", "parameters": {"order_id": "9821389421"}}
        ]
    },
    {
        "scenario": "物流信息异常停滞咨询",
        "user_query": "我买的东西怎么三天没动静了，运单号是SF1428492043，帮我看看。",
        "thought": "用户询问物流长时间未更新问题，并提供了快递运单号。我需要调用物流查询工具，如果确实超过48小时未更新，按物流SOP触发催单流程并安抚用户。",
        "actions": [
            {"tool": "query_logistics", "parameters": {"order_id": "SF1428492043"}}
        ]
    }
]
