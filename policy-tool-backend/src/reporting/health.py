import pandas as pd
from pathlib import Path
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def generate_health_report(df: pd.DataFrame, source_file: str, output_path: str = "reports/data_health_report.md"):
    """
    Generate a markdown report on data quality.
    
    Args:
        df (pd.DataFrame): The dataframe to analyze.
        source_file (str): Name of the source file.
        output_path (str): Path to save the report.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Generating health report to {path}...")
    
    total_rows = len(df)
    unique_pc6 = df['postcode'].nunique() if 'postcode' in df.columns else 0
    
    # Energy sums
    kwh_sum = df['p6_kwh_2023'].sum() if 'p6_kwh_2023' in df.columns else 0
    pv_sum = df['p6_kwh_productie_2023'].sum() if 'p6_kwh_productie_2023' in df.columns else 0
    gas_sum = df['p6_gasm3_2023'].sum() if 'p6_gasm3_2023' in df.columns else 0
    
    # Missing
    missing = df.isnull().sum()
    
    report = f"""# Data Health Report
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Source File:** {source_file}

## Summary
- **Total Rows:** {total_rows}
- **Unique PC6:** {unique_pc6}
- **Total Electricity (kWh):** {kwh_sum:,.2f}
- **Total PV Production (kWh):** {pv_sum:,.2f}
- **Total Gas (m3):** {gas_sum:,.2f}

## Missing Values
| Column | Missing Count | Percentage |
|--------|---------------|------------|
"""
    for col, count in missing.items():
        pct = (count / total_rows) * 100 if total_rows > 0 else 0
        report += f"| {col} | {count} | {pct:.2f}% |\n"
        
    with open(path, "w") as f:
        f.write(report)
        
    logger.info("Report generated.")

