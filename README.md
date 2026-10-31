# Divvy Bike-Share Data: Downloading, Pre-processing, and Importing

This guide explains how to download the Divvy trip-data archives and combine the historical and modern datasets into a unified DuckDB database and Parquet file.

> **Before you start:** The commands below use Windows PowerShell. If you're not on Windows ask an LLM to give you the equivalent installation guide.

## 1. Create the project folders

Create a folder for the project. For example:

``` text
ADA_Project/
└── Dataset/
```

The `Dataset` folder will contain the downloaded ZIP files and, later,
the extracted and organized CSV files.

## 2. Install the AWS CLI

Open Windows PowerShell and install the AWS CLI:

``` powershell
winget install Amazon.AWSCLI
```

If PowerShell was already open during installation, open a new
PowerShell window so that the `aws` command is available (I forgot this initially, this is important).

You can check the installation with:

``` powershell
aws --version
```

## 3. Download the Divvy ZIP files

Run the following command, replacing the destination with your own
`Dataset` folder:

``` powershell
aws s3 sync s3://divvy-tripdata "C:\path\to\ADA_Project\Dataset" --exclude "*" --include "*.zip" --no-sign-request
```

For example:

``` powershell
aws s3 sync s3://divvy-tripdata "C:\Users\vanoi\Downloads\ADA Project\Dataset" --exclude "*" --include "*.zip" --no-sign-request
```

## 4. Extract the ZIP files

In PowerShell, set `$datasetPath` to your `Dataset` folder and run the
complete script below. It extracts each ZIP archive into a temporary
folder, moves the CSV files into the main `Dataset` folder, and then
removes the temporary folder and original ZIP file.

``` powershell
$datasetPath = "C:\Users\vanoi\Downloads\ADA Project\Dataset"

# Get all ZIP files
$zipFiles = Get-ChildItem -Path $datasetPath -Filter "*.zip" -File

foreach ($zip in $zipFiles) {

    Write-Host "Processing $($zip.Name)..."

    # Create a temporary extraction folder
    $tempFolder = Join-Path $datasetPath ([System.IO.Path]::GetFileNameWithoutExtension($zip.Name))

    New-Item -ItemType Directory -Force -Path $tempFolder | Out-Null

    # Extract the ZIP archive
    Expand-Archive -Path $zip.FullName -DestinationPath $tempFolder -Force

    # Move CSV files into the main Dataset folder
    Get-ChildItem -Path $tempFolder -Filter "*.csv" -Recurse -File | ForEach-Object {
        Move-Item -Path $_.FullName -Destination $datasetPath -Force
    }

    # Remove the temporary extraction folder
    Remove-Item -Path $tempFolder -Recurse -Force

    # Delete the original ZIP archive
    Remove-Item -Path $zip.FullName -Force
}

Write-Host "All files processed successfully!"
```

## 5. Remove auxiliary CSV files

Inspect the extracted CSV files and remove the small auxiliary files
whose filenames begin with an underscore (`_`), they are not part of
the actual dataset, just metadata.

## 6. Organize the datasets by year

Inside `Dataset`, create a folder called `Post 2020`.

Move all data from **2020 onward (including 2020)** into this folder.

Most of the post-2020 trip files follow this naming convention:

``` text
YYYYMM-divvy-tripdata.csv
```

-   The first four digits represent the year.
-   The last two digits represent the month.

For example, `202104-divvy-tripdata.csv` represents April 2021.

**2020 exception:** The first 2020 dataset is named:

``` text
Divvy_Trips_2020_Q1.csv
```

Make sure this file is also placed in `Post 2020`.

Next, create a folder called `Pre 2020`.

Move all data from **before 2020** into this folder, including both trip
data and station data.

## 7. Separate historical trip and station data

Inside `Pre 2020`, create two folders:

-   `Stations`: contains the historical station data.
-   `Trips`: contains the historical trip data.

Move the corresponding CSV files into these folders.

## 8. Verify the folder structure

Before proceeding, check that your folder structure looks like this:

``` text
Dataset/
├── Post 2020/
│   └── *.csv
└── Pre 2020/
    ├── Stations/
    │   └── *.csv
    └── Trips/
        └── *.csv
```

Make sure that:

-   All post-2020 files, including the 2020 Q1 file, are in `Post 2020`.
-   All pre-2020 trip files are in `Pre 2020/Trips`.
-   All pre-2020 station files are in `Pre 2020/Stations`.
-   No files are missing or accidentally duplicated.

## 9. Update the paths in `import_data.ipynb`

Open `import_data.ipynb`. At this point you should also create and activate a python venv or a conda environment and install the packages that are used in this file (duckdb, pandas, glob, ipykernel). 

Use `Ctrl + F` to search for:

``` text
[TODO]
```

Replace each occurrence with the appropriate part of your own directory
path.

For example, if your dataset is located at:

``` text
C:\Users\vanoi\Downloads\ADA Project\Dataset
```

Then the paths in the notebook should look like:

``` python
stations_glob = "C:/Users/vanoi/Downloads/ADA Project/Dataset/Pre 2020/Stations/*.csv"
```

``` python
process_pre_2020(
    "C:/Users/vanoi/Downloads/ADA Project/Dataset/Pre 2020/Trips/*.csv"
)
```

``` python
post_2020_glob = "C:/Users/vanoi/Downloads/ADA Project/Dataset/Post 2020/*.csv"
```

Forward slashes (`/`) work well in these Python paths on Windows.

## 10. Run the data-import notebook

Run the first cell of `import_data.ipynb` and wait for the processing to
finish.

The processing time depends on your computer and the size of the
downloaded dataset. On my computer, it took approximately **5 minutes
and 30 seconds**.

The notebook standardizes the column names and membership categories in the 
pre-2020 trip data, and then combines it with the post-2020 trip data.

When processing finishes, it should create:

``` text
bikeshare_dataset.duckdb
bikeshare_dataset.parquet
```

The DuckDB file contains the database and the unified table. The Parquet
file contains the exported unified dataset.

## 11. Inspect and query the resulting dataset

If your computer has limited RAM, I recommend querying the dataset with
DuckDB rather than loading the entire Parquet file into Pandas.

### Option A: Query the Parquet file using DuckDB

``` python
import duckdb

con = duckdb.connect()

# Display the first five rows
post_head = con.sql(
    "SELECT * FROM 'bikeshare_dataset.parquet' LIMIT 5"
).df()

print(post_head)

# Display column names and data types
entire_df = con.sql(
    "DESCRIBE SELECT * FROM 'bikeshare_dataset.parquet'"
).df()

print("\n--- Columns and Data Types ---")
print(entire_df)

# Count the columns
num_columns = len(entire_df)
print(f"\nTotal Number of Columns: {num_columns}")

# Count the rows
row_count = con.execute(
    "SELECT COUNT(*) FROM 'bikeshare_dataset.parquet'"
).fetchone()[0]

print(f"Total Row Count: {row_count:,}")

con.close()
```

### Option B: Query the DuckDB database directly

You can also connect to the database created by the notebook:

``` python
import duckdb

con = duckdb.connect("bikeshare_dataset.duckdb", read_only=True)

# Display the first five rows
print(con.sql(
    "SELECT * FROM final_harmonized_trips LIMIT 5"
).df())

# Inspect the schema
print(con.sql(
    "DESCRIBE final_harmonized_trips"
).df())

# Count the rows
row_count = con.execute(
    "SELECT COUNT(*) FROM final_harmonized_trips"
).fetchone()[0]

print(f"Total Row Count: {row_count:,}")

con.close()
```

### Option C: Load the Parquet file into Pandas (if you have more than like 32GB of RAM)

If your computer has enough available memory, you can load the entire
Parquet dataset into a Pandas DataFrame:

``` python
import pandas as pd

df = pd.read_parquet("bikeshare_dataset.parquet")
```

------------------------------------------------------------------------

That's it, thanks for reading!
