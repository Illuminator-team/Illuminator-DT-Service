import logging
import sys
import pandas as pd
import argparse
from pathlib import Path

from src.utils.config import load_config
from src.ingestion.cdf import load_cdf_data
from src.ingestion.slp import load_slp_profiles
from src.ingestion.pvgis import fetch_pvgis_hourly
from src.processing.aggregation import aggregate_to_pc6
from src.processing.enrichment import enrich_pc6_data
from src.processing.sectors import assign_sector_weights
from src.processing.profiles import get_normalized_profiles
from src.processing.engine import generate_hourly_profiles
from src.models.pc6_schema import PC6AggregatedSchema

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Alkmaar Energy Transition Policy Tool")
    parser.add_argument("--pc6", type=str, help="Generate profile for a specific PC6 code (e.g., 1813KJ)")
    parser.add_argument("--full", action="store_true", help="Run full-scale pipeline for all PC6s")
    parser.add_argument("--input", type=str, default="data/raw/energiedata-match-gemeentecode=[GM0361]-csv.csv", help="Path to input CDF CSV file")
    parser.add_argument("--output-dir", type=str, default="data/processed", help="Directory for output files")
    parser.add_argument("--electrification", type=float, default=0.0, help="Fraction (0.0-1.0) of gas heat to switch to Heat Pumps")
    args = parser.parse_args()

    if not args.pc6 and not args.full:
        parser.print_help()
        sys.exit(0)

    logger.info("Starting Policy Tool Pipeline...")
    
    try:
        # 1. Load Config
        config = load_config()
        logger.info("Configuration loaded.")
        
        # 2. Ingestion
        # 2.1 CDF Data
        cdf_path = args.input
        logger.info(f"Step 2.1: Loading CDF data from {cdf_path}...")
        
        try:
            cdf_df = load_cdf_data(cdf_path, target_gemeente="GM0361")
        except FileNotFoundError:
            logger.error(f"CRITICAL: Real CDF file not found at {cdf_path}. Please place the file there.")
            sys.exit(1)
            
        # 2.3 PV & Temp Profile
        logger.info("Step 2.3: Fetching PV & Temperature Profile (PVGIS)...")
        pv_profile, temp_profile = None, None
        try:
            lat, lon = 52.63, 4.75
            pv_profile, temp_profile = fetch_pvgis_hourly(lat, lon)
        except Exception as e:
            logger.warning(f"Failed to fetch environmental profiles: {e}. Profiles will use defaults.")
            
        # 3. Processing (Annual Aggregation)
        logger.info("Step 3: Aggregating to PC6...")
        agg_df = aggregate_to_pc6(cdf_df)
        
        # 2.2 SLP Data
        logger.info("Step 2.2: Verifying SLP profiles...")
        slp_profiles = get_normalized_profiles(temp_series=temp_profile)
            
        # 4. Enrichment & Sector Split
        logger.info("Step 4: Enriching and assigning sectors...")
        enriched_df = enrich_pc6_data(agg_df, electrification_fraction=args.electrification)
        final_df = assign_sector_weights(enriched_df)
        
        # 5. Validation
        logger.info("Step 5: Validating Output Schema...")
        PC6AggregatedSchema.validate(final_df)
        
        # 6. Annual Output
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path_annual = output_dir / "pc6_annual_data.csv"
        final_df.to_csv(output_path_annual)
        
        # 7. Hourly Output
        if args.pc6:
            pc6_code = args.pc6.upper().replace(" ", "")
            logger.info(f"Step 7: Generating profile for single PC6: {pc6_code}")
            
            if pc6_code not in final_df.index:
                logger.error(f"PC6 {pc6_code} not found in the processed dataset.")
                sys.exit(1)
                
            pc6_row = final_df.loc[[pc6_code]]
            
            # PC6 Summary
            pc6_heat_gross = pc6_row['heat_gross_annual'].iloc[0]
            pc6_nongas_share = pc6_row['current_electrification_share'].iloc[0]
            
            logger.info("-" * 40)
            logger.info(f"PC6 SUMMARY: {pc6_code}")
            logger.info(f"Total Heat Demand:  {pc6_heat_gross/1e3:.1f} MWh_th")
            logger.info(f"Non-Gas Heat Share: {pc6_nongas_share:.1%}")
            logger.info("-" * 40)

            # Use generator but just for one
            for df_pc6 in generate_hourly_profiles(pc6_row, slp_profiles, pv_profile=pv_profile):
                # Format for tool output (4 columns as per strategy.md)
                tool_output = df_pc6[[
                    "timestamp",
                    "elec_gross_kwh",
                    "pv_gen_kwh",
                    "elec_net_kwh",
                    "heat_gross_delivered_kwh_th",
                    "hp_elec_input_kwh",
                    "gas_input_kwh"
                ]].copy()
                
                # Rename to friendly names if needed or keep as is. 
                # Strategy says: electrical demand gross, pv generation, electrical demand net, and heat demand
                tool_output.columns = [
                    "timestamp",
                    "electrical_demand_gross_kwh",
                    "pv_generation_kwh",
                    "electrical_demand_net_kwh",
                    "heat_demand_kwh_th",
                    "hp_electricity_input_kwh",
                    "gas_input_kwh"
                ]
                
                output_fn = output_dir / f"pc6_profile_{pc6_code}.csv"
                tool_output.to_csv(output_fn, index=False)
                logger.info(f"Profile saved to {output_fn}")
                break # only one expected

        if args.full:
            logger.info("Step 7: Generating Hourly Profiles (Full Scale)...")
            output_path_hourly = output_dir / "pc6_hourly_full.csv"
            
            first_chunk = True
            total_rows = 0
            buffer = []
            buffer_size = 50 # Keep buffer size for I/O efficiency
            count = 0
            
            for df_pc6 in generate_hourly_profiles(final_df, slp_profiles, pv_profile=pv_profile):
                buffer.append(df_pc6)
                count += 1
                
                # Heartbeat to prevent timeout
                if count % 10 == 0:
                    logger.info(f"Processed {count} profiles so far...")
                
                if len(buffer) >= buffer_size:
                    chunk_df = pd.concat(buffer, ignore_index=True)
                    mode = 'w' if first_chunk else 'a'
                    header = first_chunk
                    chunk_df.to_csv(output_path_hourly, mode=mode, header=header, index=False)
                    total_rows += len(chunk_df)
                    first_chunk = False
                    buffer = []
                    logger.info(f"Written chunk. Total rows: {total_rows}")
            
            if buffer:
                chunk_df = pd.concat(buffer, ignore_index=True)
                mode = 'w' if first_chunk else 'a'
                header = first_chunk
                chunk_df.to_csv(output_path_hourly, mode=mode, header=header, index=False)
                total_rows += len(chunk_df)
                logger.info(f"Written {total_rows} rows...")
                
            logger.info(f"Full scale generation complete. Output at {output_path_hourly}")
        
        # Municipal Summary (Always show overall context, but label it clearly)
        total_heat_gross = final_df['heat_gross_annual'].sum()
        total_heat_nongas = final_df['heat_nongas_estimated'].sum()
        municipal_electrification = (total_heat_nongas / total_heat_gross) if total_heat_gross > 0 else 0.0
        
        if args.full:
            logger.info("-" * 40)
            logger.info(f"MUNICIPAL SUMMARY (Alkmaar - Full Dataset)")
            logger.info(f"Total Heat Demand (Gross): {total_heat_gross/1e6:.2f} GWh_th")
            logger.info(f"Non-Gas Heat Share:        {municipal_electrification:.1%} (includes District Heat)")
            logger.info("-" * 40)

        logger.info("Pipeline completed successfully.")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()