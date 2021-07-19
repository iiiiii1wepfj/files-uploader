import humanfriendly

the_size = humanfriendly.parse_size("700mb", binary=False)
print(the_size)
