# Lesson: a DETACHED_PROCESS parent makes every console child open its own window (t_58ea23a5)

DETACHED_PROCESS means "no console". Any console-subsystem child it starts (agent CLI, node, taskkill) then allocates a new visible one. Hiding the scheduler hop (wscript //B) is not enough if a later Popen detaches.

Rule: to run a background worker on Windows use CREATE_NO_WINDOW (hidden console the children inherit), not DETACHED_PROCESS. Prove it with a control: launch the same probe with the old flags, confirm the window list sees a new window, then show the new flags see none. A "no window" test that cannot see a window proves nothing.
