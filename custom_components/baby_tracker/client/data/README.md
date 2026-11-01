# Growth reference data

`who-{boys,girls}-{weight,length,head}.csv` hold the WHO Child Growth Standards
(2006) for 0-24 months: weight-for-age (kg), length-for-age (cm, recumbent) and
head-circumference-for-age (cm). Each row is one month with the LMS parameters
(`L`, `M`, `S`) and the tabulated 2nd to 98th percentile values.

They are the US CDC's mirror of the WHO tables, unmodified, as downloaded from:

- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Boys-Weight-for-age-Percentiles.csv
- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Girls-Weight-for-age%20Percentiles.csv
- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Boys-Length-for-age-Percentiles.csv
- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Girls-Length-for-age-Percentiles.csv
- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Boys-Head-Circumference-for-age-Percentiles.csv
- https://ftp.cdc.gov/pub/Health_Statistics/NCHS/growthcharts/WHO-Girls-Head-Circumference-for-age-Percentiles.csv

The CDC publishes these as US government work (public domain). The underlying
standards are the WHO Child Growth Standards:
https://www.who.int/tools/child-growth-standards/standards

`insights.py` reads `Month`, `L`, `M` and `S` and interpolates between months.
