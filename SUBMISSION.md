# Submission files

Upload these three files at [the HackerRank submission page](https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission):

| Required artifact | File |
| --- | --- |
| Predictions for all 250 requests | [output.csv](output.csv) |
| Runnable code and usage report | [code.zip](code.zip) |
| Development transcript | Local `log.txt`, as specified by the challenge README; [chat_transcript.txt](chat_transcript.txt) is an abridged supplementary record |

`log.txt` is intentionally gitignored and must be selected from the working checkout when uploading. The ZIP contains `evaluation/usage_report.md`, image-extraction facts, setup instructions, tests, and evaluation evidence.

To regenerate and check the files from the repository root:

```sh
python3 code/main.py
python3 code/main.py --samples
PYTHONPATH=code python3 -m unittest discover -s code/evaluation -p 'test_*.py' -v
python3 code/evaluation/package_solution.py
python3 code/evaluation/verify_package.py
```

No contest upload is performed by these commands. The technical checks pass under the documented forecast model; remaining sample discrepancies are disclosed in [results.md](code/evaluation/results.md).
