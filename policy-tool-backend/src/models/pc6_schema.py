import pandera as pa
import pandas as pd
from pandera.typing import Series, Index

class PC6AggregatedSchema(pa.DataFrameModel):
    """
    Schema for the aggregated PC6 annual data.
    """
    
    # Index is postcode
    # postcode: Index[str] = pa.Index(str_matches=r"^\d{4}[A-Za-z]{2}$", unique=True, name="postcode")
    # Using column check if reset_index() is used, or index check. 
    # Let's assume reset_index() for validation simplicity or handle index.
    
    # Aggregated columns
    p6_kwh_2023: Series[float] = pa.Field(ge=0, nullable=True)
    p6_kwh_productie_2023: Series[float] = pa.Field(ge=0, nullable=True)
    p6_gasm3_2023: Series[float] = pa.Field(ge=0, nullable=True)
    p6_gas_aansluitingen_2023: Series[float] = pa.Field(ge=0, nullable=True)
    p6_grondbeslag_m2: Series[float] = pa.Field(ge=0, nullable=True)
    
    pc6_gemiddelde_woz_waarde_woning: Series[float] = pa.Field(ge=0, nullable=True)
    pc6_eigendomssituatie_perc_koop: Series[float] = pa.Field(ge=0, le=100, nullable=True)
    pc6_eigendomssituatie_perc_huur: Series[float] = pa.Field(ge=0, le=100, nullable=True)
    pc6_eigendomssituatie_aantal_woningen_corporaties: Series[float] = pa.Field(ge=0, nullable=True)
    
    # Enriched columns
    gas_input_kwh_annual: Series[float] = pa.Field(ge=0, nullable=True)
    heat_gross_annual: Series[float] = pa.Field(ge=0, nullable=True)
    
    address_count: Series[int] = pa.Field(ge=1)
    
    # Profile Weights
    weight_E1: Series[float] = pa.Field(ge=0, le=1, nullable=True)
    weight_E2: Series[float] = pa.Field(ge=0, le=1, nullable=True)
    weight_G1: Series[float] = pa.Field(ge=0, le=1, nullable=True)
    weight_G2: Series[float] = pa.Field(ge=0, le=1, nullable=True)

    class Config:
        strict = False # Allow extra columns like region codes
        coerce = True  # Auto-convert types (e.g. int -> float)
        
    @pa.dataframe_check
    def check_weights_sum_to_one(cls, df: pd.DataFrame) -> Series[bool]:
        # Check Elec weights
        e_sum = df["weight_E1"] + df["weight_E2"]
        # Check Gas weights
        g_sum = df["weight_G1"] + df["weight_G2"]
        
        # Use a small tolerance for float arithmetic
        return (e_sum.between(0.99, 1.01)) & (g_sum.between(0.99, 1.01))
