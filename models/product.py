from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TargetProduct(BaseModel):
    """Payload model matching your scrape_single_tcin output."""

    tcin: str = Field(..., description="Target Item Number")
    title: Optional[str] = Field(None, description="Product title")
    brand: Optional[str] = Field(None, description="Brand name")
    price: Optional[float] = Field(None, description="Numeric price")
    formatted_price: Optional[str] = Field(None, description="Formatted price string")
    rating: Optional[float] = Field(None, description="Average rating score")
    review_count: Optional[int] = Field(None, description="Total review count")
    primary_image: Optional[str] = Field(None, description="Primary image URL")
    description: Optional[str] = Field(None, description="Product description")
    sample_reviews: List[Dict[str, Any]] = Field(default_factory=list)