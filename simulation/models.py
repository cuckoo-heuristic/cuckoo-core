from django.db import models


class RSU(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Vehicle(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Task(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
