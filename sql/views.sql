-- =============================================================================
-- Reporting views: the "clean source for dashboards".
-- BI tools (Metabase, Superset, Power BI, Tableau) and the bundled web UI
-- read these views rather than the raw tables.
-- =============================================================================

-- Denormalised, revenue-recognised sales (cancelled/returned orders excluded).
CREATE OR REPLACE VIEW reporting.v_sales AS
SELECT
    f.order_id,
    f.order_date,
    date_trunc('month', f.order_date)::date AS order_month,
    f.customer_id,
    c.full_name                             AS customer_name,
    c.region,
    c.country,
    f.product_id,
    p.product_name,
    p.category,
    f.channel,
    f.quantity,
    f.discount,
    f.currency,
    f.revenue_usd
FROM reporting.fact_orders f
JOIN reporting.dim_customers c USING (customer_id)
JOIN reporting.dim_products  p USING (product_id)
WHERE f.status IN ('completed', 'shipped');

CREATE OR REPLACE VIEW reporting.v_monthly_revenue AS
SELECT
    order_month,
    COUNT(*)                                        AS orders,
    COUNT(DISTINCT customer_id)                     AS customers,
    SUM(quantity)                                   AS units,
    ROUND(SUM(revenue_usd), 2)                      AS revenue_usd,
    ROUND(SUM(revenue_usd) / NULLIF(COUNT(*), 0), 2) AS avg_order_value_usd
FROM reporting.v_sales
GROUP BY order_month;

CREATE OR REPLACE VIEW reporting.v_revenue_by_category AS
SELECT category, COUNT(*) AS orders, ROUND(SUM(revenue_usd), 2) AS revenue_usd
FROM reporting.v_sales
GROUP BY category;

CREATE OR REPLACE VIEW reporting.v_revenue_by_region AS
SELECT region, COUNT(*) AS orders, COUNT(DISTINCT customer_id) AS customers,
       ROUND(SUM(revenue_usd), 2) AS revenue_usd
FROM reporting.v_sales
GROUP BY region;

CREATE OR REPLACE VIEW reporting.v_top_products AS
SELECT product_id, product_name, category,
       SUM(quantity) AS units, ROUND(SUM(revenue_usd), 2) AS revenue_usd,
       RANK() OVER (ORDER BY SUM(revenue_usd) DESC) AS revenue_rank
FROM reporting.v_sales
GROUP BY product_id, product_name, category;

-- Order fulfilment funnel across *all* statuses (not only recognised revenue).
CREATE OR REPLACE VIEW reporting.v_order_status AS
SELECT status, COUNT(*) AS orders, ROUND(SUM(revenue_usd), 2) AS gross_usd
FROM reporting.fact_orders
GROUP BY status;

-- Data quality per run, ready to chart.
CREATE OR REPLACE VIEW etl.v_run_quality AS
SELECT
    r.run_id,
    r.started_at,
    r.status,
    r.rows_extracted,
    r.rows_loaded,
    r.rows_rejected,
    r.rows_warned,
    CASE WHEN r.rows_extracted = 0 THEN NULL
         ELSE ROUND(100.0 * (r.rows_extracted - r.rows_rejected) / r.rows_extracted, 2)
    END AS pass_rate_pct
FROM etl.pipeline_runs r;
