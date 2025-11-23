#!/bin/sh

export LC_ALL=C
offset="$(od -An -vtx1 -N 64 -- "$1" | awk '
	BEGIN {
		for (i = 0; i < 16; i++) {
			c = sprintf("%x", i)
			H[c] = i
			H[toupper(c)] = i
		}
	}
	{
		elfHeader = elfHeader " " $0
	}
	END {
		$0 = toupper(elfHeader)
		if ($5 == "02") is64 = 1; else is64 = 0
		if ($6 == "02") isBE = 1; else isBE = 0
		if (is64) {
			if (isBE) {
				shoff = $41 $42 $43 $44 $45 $46 $47 $48
				shentsize = $59 $60
				shnum = $61 $62
			} else {
				shoff = $48 $47 $46 $45 $44 $43 $42 $41
				shentsize = $60 $59
				shnum = $62 $61
			}
			} else {
			if (isBE) {
				shoff = $33 $34 $35 $36
				shentsize = $47 $48
				shnum = $49 $50
			} else {
				shoff = $36 $35 $34 $33
				shentsize = $48 $47
				shnum = $50 $49
			}
		}
		print parsehex(shoff) + parsehex(shentsize) * parsehex(shnum)
	}
	function parsehex(v, i, r) {
		r = 0
		for (i = 1; i <= length(v); i++)
			r = r * 16 + H[substr(v, i, 1)]
		return r
	}'
)"

if [ -n "$offset" ]; then
	echo "$offset"
else
	exit 1
fi
