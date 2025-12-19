"""Author schema models."""

from typing import Optional

from pydantic import BaseModel, Field


class AuthorSchema(BaseModel):
    """Schema representing a document author."""

    given_name: Optional[str] = Field(None, description="Author's given/first name")
    family_name: str = Field(..., description="Author's family/last name")
    orcid: Optional[str] = Field(None, description="Author's ORCID identifier")
    affiliation: Optional[str] = Field(None, description="Author's institutional affiliation")
    email: Optional[str] = Field(None, description="Author's email address")
    sequence: Optional[str] = Field(
        None, description="Position in author list (first, additional)"
    )

    @property
    def full_name(self) -> str:
        """Return the full name of the author."""
        if self.given_name:
            return f"{self.given_name} {self.family_name}"
        return self.family_name

    @property
    def normalized_name(self) -> str:
        """Return a normalized version of the name for matching."""
        name = self.full_name.lower().strip()
        # Remove extra whitespace
        return " ".join(name.split())
