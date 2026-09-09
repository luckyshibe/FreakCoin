#ifndef FREAKCHAIN_SECURECONFIG_H
#define FREAKCHAIN_SECURECONFIG_H

#include <string>

// Creates a new configuration only. Existing files (including symlinks) are
// never replaced. On failure, error contains no generated credentials.
bool CreateRPCConfig(const std::string& path, std::string& error);

#endif
