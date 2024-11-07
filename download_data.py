import gdown
import pandas as pd


dataset_file_path = "python_stackover_flow_dataset.csv"
url = 'https://drive.google.com/uc?id=1VuXXeiMlGn0utMZWrEXpDSkoqx8hC630'
gdown.download(url, dataset_file_path, quiet=False)


df =pd.read_csv(dataset_file_path)
print(f"Shape of the dataset: {df.shape}")
print(df.head())