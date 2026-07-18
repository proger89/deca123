# Passive-safe gate cell

The dimension gate is first and mechanically rests toward C. The shape gate is second and rests toward D. Passing to B requires both motors to reach 1.2 rad and both independent position sensors to confirm within 0.02 rad before ZPA release.

Each `FailSafeGate` uses an 18 N·m/rad return spring, 2.35 N·m·s/rad damping, 0/1.25 rad hard stops, a 35 N·m torque limit and a `PositionSensor`. Removing motor torque therefore returns the blade physically; controller commands are not the safety mechanism.

```text
A / sensing -> [dimension gate; rest C] -> [shape gate; rest D] -> B
                         |                         |
                         +---- C                  +---- D
```

The route state machine holds the following item until matching exit confirmation. Power loss, E-stop, jam, position failure, missing exit and route mismatch enter a latched FAULT/ESTOP state; an explicit reset is required.
