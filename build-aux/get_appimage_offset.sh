#!/usr/bin/bash

ELFSIZE=$(readelf -h $1)
START_OF_SECTION=$(echo $ELFSIZE | grep -oP "(?<=Start of section headers: )[0-9]+")
SECTION_SIZE=$(echo $ELFSIZE | grep -oP "(?<=Size of section headers: )[0-9]+")
SECTION_NO=$(echo $ELFSIZE | grep -oP "(?<=Number of section headers: )[0-9]+")
APPIMG_OFFSET=$(( $START_OF_SECTION + $SECTION_SIZE * $SECTION_NO ))

echo $APPIMG_OFFSET


