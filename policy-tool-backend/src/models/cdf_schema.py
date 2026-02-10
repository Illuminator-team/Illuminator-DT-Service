import pandera as pa
from pandera.typing import Series

class CDFSchema(pa.DataFrameModel):
    """
    Schema for the Common Data Factory (CDF) raw export.
    Expects standardized (lowercase) column names.
    """
    
    postcode: Series[str] = pa.Field(coerce=True, str_matches=r"^\d{4}[A-Za-z]{2}$", description="PC6 (e.g. 1234AB)")
    gemeentecode: Series[str] = pa.Field(coerce=True, eq="GM0361", description="Municipality code (Alkmaar)")
    
    # Energy columns (can be nullable if data is missing for some addresses)
    p6_kwh_2023: Series[float] = pa.Field(ge=0, nullable=True, coerce=True)
    p6_kwh_productie_2023: Series[float] = pa.Field(ge=0, nullable=True, coerce=True)
    p6_gasm3_2023: Series[float] = pa.Field(ge=0, nullable=True, coerce=True)
    p6_gas_aansluitingen_2023: Series[float] = pa.Field(ge=0, nullable=True, coerce=True)
    
    # Building attributes (used for sector split)
    gebruiksdoelen: Series[str] = pa.Field(nullable=True, coerce=True)
    oppervlakte: Series[float] = pa.Field(ge=0, nullable=True, coerce=True)
    pand_bouwjaar: Series[float] = pa.Field(ge=1000, le=2100, nullable=True, coerce=True) # Year as float often
    
    class Config:
        strict = False # Allow extra columns
        coerce = True
