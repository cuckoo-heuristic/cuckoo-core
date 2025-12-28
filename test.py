from monarch_pylib.models import transmission

print(transmission.distance_1d(30, 1.5))

print(transmission.distance_2d(0, 0, 0, 4))

print(transmission.distance_3d(0, 0, 0, 0, 0, 2))

time = 10

path = [[0, 0], [3, 4], [6, 8]]

length = transmission.path_length_2d(path)
# طول مسیر

velocity = transmission.speed_vehicle(length, time)
# سرعت

print(length)

print(velocity)

print(transmission.current_position(time, 0, path))
print(transmission.current_position(time, 5, path))
print(transmission.current_position(time, 10, path))
# مکان فعلی ماشین بر حسب زمان
