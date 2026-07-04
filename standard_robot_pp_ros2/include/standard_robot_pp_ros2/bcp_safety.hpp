// Copyright 2026
// Licensed under the Apache License, Version 2.0.

#ifndef STANDARD_ROBOT_PP_ROS2__BCP_SAFETY_HPP_
#define STANDARD_ROBOT_PP_ROS2__BCP_SAFETY_HPP_

#include <cstdint>
#include <vector>

namespace standard_robot_pp_ros2
{

enum class BcpChecksumResult
{
  INVALID_STRUCTURE,
  INVALID_SUM,
  INVALID_ADD,
  STANDARD,
  LEGACY
};

BcpChecksumResult verifyBcpChecksums(const std::vector<uint8_t> & frame);

struct CBoardOdomSample
{
  double vx = 0.0;
  double vy = 0.0;
  double wz = 0.0;
  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
};

CBoardOdomSample applyOdomAxisInversion(
  const CBoardOdomSample & sample, bool invert_x, bool invert_y, bool invert_yaw);

struct OdomGuardConfig
{
  double max_abs_position_m = 100.0;
  double max_linear_speed_mps = 12.0;
  double max_angular_speed_radps = 15.0;
  double position_jump_margin_m = 0.10;
  double yaw_jump_margin_rad = 0.15;
  int64_t reset_gap_ms = 500;
  double reset_origin_radius_m = 1.0;
  uint32_t reset_confirm_frames = 3;
};

enum class OdomRejectReason
{
  NONE,
  NON_FINITE,
  POSITION_RANGE,
  LINEAR_SPEED_RANGE,
  ANGULAR_SPEED_RANGE,
  POSITION_JUMP,
  YAW_JUMP
};

const char * odomRejectReasonName(OdomRejectReason reason);

struct OdomGuardResult
{
  bool accepted = false;
  bool reset_compensated = false;
  OdomRejectReason reason = OdomRejectReason::NONE;
  CBoardOdomSample sample;
};

class OdomGuard
{
public:
  explicit OdomGuard(const OdomGuardConfig & config = OdomGuardConfig{});

  void setConfig(const OdomGuardConfig & config);
  void reset();
  OdomGuardResult process(const CBoardOdomSample & raw, int64_t receive_time_ms);

private:
  static double normalizeAngle(double angle);
  bool sampleWithinAbsoluteLimits(const CBoardOdomSample & sample, OdomRejectReason & reason) const;
  bool deltaIsPlausible(
    const CBoardOdomSample & from, const CBoardOdomSample & to, int64_t dt_ms,
    OdomRejectReason & reason) const;
  bool updateResetCandidate(const CBoardOdomSample & raw, int64_t receive_time_ms);
  CBoardOdomSample transformSample(const CBoardOdomSample & raw) const;
  void acceptSample(const CBoardOdomSample & raw, int64_t receive_time_ms);
  void beginNewEpoch(const CBoardOdomSample & raw, int64_t receive_time_ms);

  OdomGuardConfig config_;
  bool initialized_ = false;
  CBoardOdomSample last_raw_;
  CBoardOdomSample last_output_;
  int64_t last_receive_time_ms_ = 0;

  double epoch_yaw_offset_ = 0.0;
  double epoch_translation_x_ = 0.0;
  double epoch_translation_y_ = 0.0;

  uint32_t reset_candidate_count_ = 0;
  CBoardOdomSample reset_candidate_last_;
  int64_t reset_candidate_time_ms_ = 0;
};

}  // namespace standard_robot_pp_ros2

#endif  // STANDARD_ROBOT_PP_ROS2__BCP_SAFETY_HPP_
