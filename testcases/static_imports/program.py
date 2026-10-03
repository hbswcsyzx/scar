"""External source-analysis testcase; SCAR must not execute this program."""
import arith_data as source

answer = source.PUBLIC[0][1]

raise RuntimeError("This testcase is for nonexecuting analysis only")
