#!/usr/bin/env bash

# Start the timer (if not already enabled/started)
sudo systemctl start dashboard-restart.timer

# Trigger the timer’s service immediately (no waiting)
sudo systemctl start dashboard-restart.service

# Check that it ran
sudo systemctl status dashboard-restart.service
