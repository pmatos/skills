from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Address:
    country: str
    postal_code: str

    def normalized(self) -> "Address":
        return replace(
            self,
            country=self.country.strip().upper(),
            postal_code=self.postal_code.replace(" ", "").upper(),
        )
