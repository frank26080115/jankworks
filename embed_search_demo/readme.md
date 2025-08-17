In a few of the things you've helped me with, the subject of using "embeddings" for text searching has come up a lot. Can you please write a python demonstrator for me? the input parameter is a path to a text file (with english sentences), and a search phrase (specified within double quotations on the command line), and it should output the top three results with their scores indicated.

----

Got you. Here’s a small, self-contained Python script that uses sentence embeddings (via sentence-transformers) to find the 3 most semantically similar sentences to a query.

Install:

`pip install -U sentence-transformers torch numpy`

Example run:

`python embed_search.py sample.txt "freedom and equality"`

`python embed_search.py sample.txt "cemetery dedication"`
