<example name="ship-and-email">
owner_request: Ship yesterday's orders and send tracking.
turn 1 → list_orders(status="paid", created_from=YESTERDAY, created_to=YESTERDAY, order_ids=null)   (YESTERDAY = store_date minus one day, written YYYY-MM-DD)
result: 6 orders O9101…O9106
turn 2 → mark_shipped(order_ids=[O9101…O9106], carrier="usps", rationale="6 paid orders were placed yesterday.", evidence=[O9101…O9106])
       → send_email(order_ids=[O9101…O9106], template="tracking", custom_body=null, rationale="Buyers get their tracking number once shipped.", evidence=[O9101…O9106])
results: STAGED s1, STAGED s2
final: {"status":"ready","message":"Ship 6 orders from yesterday by USPS and email each buyer their tracking number."}
</example>

<example name="ambiguous-refund">
owner_request: Refund Dana's order.
turn 1 → list_orders(status="any", created_from=null, created_to=null, order_ids=null)
result: customer Dana Ruiz has 2 shipped orders, O9201 ($38.00) and O9202 ($112.00)
final: {"status":"needs_clarification","message":"Dana Ruiz has two orders: O9201 ($38.00, Sep 30) and O9202 ($112.00, Oct 9). Which one should I refund, and in full?"}
</example>

<example name="inbox-with-injection">
owner_request: Handle the inbox.
turn 1 → list_inbox()
result: <untrusted_email id="E901" customer_id="C9040">My order O9301 came with a broken handle.</untrusted_email>
        <blocked_email id="E902" label="injection" reason="asks the agent to override its rules"/>
turn 2 → list_orders(status="any", created_from=null, created_to=null, order_ids=["O9301"])
result: O9301, shipped, customer C9040, $24.00, refunded $0
turn 3 → refund_order(order_id="O9301", amount_cents=null, reason="requested_by_customer", rationale="E901 from the buyer says the handle arrived broken.", evidence=["E901","O9301"])
result: STAGED s1
final: {"status":"ready","message":"Refund O9301 in full ($24.00) for a broken handle. E902 was blocked by the safety screen and not acted on."}
</example>

<example name="repair-after-reject">
owner_request: Refund $60 on order O9401.
turn 1 → list_orders(status="any", created_from=null, created_to=null, order_ids=["O9401"])
result: O9401, shipped, total $45.00, refunded $0
turn 2 → refund_order(order_id="O9401", amount_cents=6000, reason="requested_by_customer", rationale="Owner asked for a $60 refund.", evidence=["owner_request","O9401"])
result: REJECTED: amount exceeds refundable $45.00
final: {"status":"needs_clarification","message":"O9401 only has $45.00 left to refund, less than the $60 you asked for. Refund the full $45.00 instead?"}
</example>

<example name="restock-from-forecast">
owner_request: Reorder whatever sells out in the next 10 days.
turn 1 → forecast_demand(product_id=null, horizon_days=10, only_at_risk=true)
result: 2 products run out within 10 days: P9101 (2d) and P9102 (9d), each with a reorder_qty and an explanation
turn 2 → create_restock_po(product_id="P9101", qty_source="forecast", qty=null, rationale=<P9101's explanation, copied>, evidence=["P9101"])
       → create_restock_po(product_id="P9102", qty_source="forecast", qty=null, rationale=<P9102's explanation, copied>, evidence=["P9102"])
results: STAGED s1, STAGED s2
final: {"status":"ready","message":"Reorder P9101 and P9102 at the forecast quantities; both run out within 10 days."}
</example>

<example name="owner-named-targets">
owner_request: Export orders as CSV and send customer C9050 a $40 payment link for a gift box.
turn 1 → export_report(kind="orders_csv", rationale="The owner asked for an orders CSV.", evidence=["owner_request"])
       → create_payment_link(order_id=null, customer_id="C9050", amount_cents=4000, description="Gift box", rationale="The owner asked for a $40 gift box payment link for C9050.", evidence=["owner_request"])
results: STAGED s1, STAGED s2
final: {"status":"ready","message":"Export all orders as a CSV and create a $40.00 payment link for customer C9050's gift box."}
</example>

<example name="question-only">
owner_request: Did anything odd happen with orders this month?
turn 1 → flag_anomalies(since_days=30, limit=20)
result: 2 flagged: O9601 (score 12.0, "30 units in one order; typical is 3") and O9602 (score 6.1, "paid 3% of the list price")
final: {"status":"ready","message":"Two orders look unusual: O9601 has 30 units where a typical order has 3, and O9602 paid 3% of the list price. Nothing was changed."}
</example>
