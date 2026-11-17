# Implementation Plan: Prosperity & Growth Metrics

This document outlines how the data and agent lanes will calculate the four key pillars of the "Targeted Prosperity" track: ROI, Equity, Resilience, and Risk.

## 1. ROI Metrics (Job Creation & Cost)
**Goal:** Estimate direct jobs and calculate the downstream employment multiplier.
**How to collect:**
1.  **Direct Jobs:** Execute a SQL script to geographically allocate jobs from the `employer_blocks` table to the `businesses` table based on proximity. This creates a baseline `estimated_jobs` attribute for every business.
2.  **Indirect Jobs (Multiplier):** Create the BigQuery Property Graph. The agent runs a backward GQL traversal `MATCH p = (applicant:Business)<-[s:Supplies]-{1,3}(supplier:Business)`. The tool calculates indirect jobs by summing the `estimated_jobs` of the suppliers, weighted by the `intensity` of the supply edge.
3.  **Cost per Job:** The agent takes the proposed grant amount and divides it by (Direct Jobs + Indirect Jobs).

## 2. Equity Metrics (Need Targeting)
**Goal:** Ensure the jobs created are accessible to high-need populations.
**How to collect:**
1.  **Neighborhood Poverty:** The agent queries the `tract_demographics` table using the applicant's census tract to find the baseline poverty rate.
2.  **Supply Chain Poverty Footprint:** During the GQL traversal (see ROI), the agent collects the census tract IDs for all downstream suppliers. It queries `tract_demographics` for those tracts and calculates a weighted average poverty rate for the entire supply chain.

## 3. Resilience Metrics (Diversification)
**Goal:** Prevent the "Walmart Effect" by ensuring the grant doesn't over-concentrate economic reliance on one industry or a single massive supplier.
**How to collect:**
1.  **Industry Concentration Risk:** A SQL query calculates the percentage of total corridor jobs belonging to each NAICS code. The agent checks this to ensure it isn't funding an industry that already dominates the corridor.
2.  **Supply Chain Breadth & Variety:** During the GQL traversal, the agent counts the `COUNT(DISTINCT supplier.business_id)` to measure breadth, and `COUNT(DISTINCT supplier.naics)` to measure the variety of industries supported by the applicant.

## 4. Risk & Context Metrics
**Goal:** Identify fragile supply chains that are at risk of systemic collapse.
**How to collect:**
1.  **Fragility Flag (SBA Charge-offs):** The agent runs a standard SQL `JOIN` between the suppliers identified in the GQL traversal and the `borrowed_from` table. It flags the applicant if `charged_off = TRUE` for any business in their supply chain, indicating severe financial instability in their network.
