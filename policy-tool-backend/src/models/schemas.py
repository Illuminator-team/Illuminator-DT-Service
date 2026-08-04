import pandera as pa
from pandera.typing import Series, DateTime

class PC6ProfileSchema(pa.DataFrameModel):
    """
    Schema for hourly PC6 demand profiles.
    Follows Strategy Section 9.1.
    """
    
    # Identifiers
    pc6: Series[str] = pa.Field(coerce=True, description="Postcode 6 (e.g., '1234AB')")
    timestamp: Series[DateTime] = pa.Field(coerce=True, description="Hourly timestamp")

    # Electricity
    elec_gross_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Gross electricity demand before PV")
    pv_gen_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Local PV generation")
    elec_net_kwh: Series[float] = pa.Field(nullable=True, description="Net load (Gross - PV). Negative = Export")
    grid_import_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Grid import (max(Net, 0))")
    grid_export_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Grid export (max(-Net, 0))")

    # Heat
    heat_gross_delivered_kwh_th: Series[float] = pa.Field(ge=0, nullable=True, description="Gross useful heat demand (space + DHW)")
    heat_net_external_input_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Net external energy input for heat (gas/elec) after COP")
    
    # Optional breakdowns
    gas_input_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Gas energy input for heat")
    hp_elec_input_kwh: Series[float] = pa.Field(ge=0, nullable=True, description="Electricity input for Heat Pumps")

    class Config:
        strict = True  # Do not allow unknown columns (can relax later if needed)
        coerce = True
