// Copyright 2026
// Licensed under the Apache License, Version 2.0.

#include "standard_robot_pp_ros2/bcp_safety.hpp"

#include <algorithm>
#include <cmath>

namespace standard_robot_pp_ros2
{
namespace
{
constexpr double PI = 3.14159265358979323846;
}

BcpChecksumResult verifyBcpChecksums(const std::vector<uint8_t> & frame)
{
  if (frame.size() < 6U || frame.size() != static_cast<size_t>(frame[3]) + 6U) {
    return BcpChecksumResult::INVALID_STRUCTURE;
  }

  uint32_t sum = 0U;
  for (size_t i = 0; i < frame.size() - 2U; ++i) {
    sum += frame[i];
  }
  if (frame[frame.size() - 2U] != static_cast<uint8_t>(sum & 0xFFU)) {
    return BcpChecksumResult::INVALID_SUM;
  }

  uint32_t standard_sum = frame[0] + frame[1];
  uint32_t standard_add = frame[0] + standard_sum;
  for (size_t i = 2U; i < frame.size() - 2U; ++i) {
    standard_sum += frame[i];
    standard_add += standard_sum;
  }

  uint32_t legacy_sum = frame[0] + frame[1] + frame[2] + frame[3];
  uint32_t legacy_add = legacy_sum;
  for (size_t i = 4U; i < frame.size() - 2U; ++i) {
    legacy_sum += frame[i];
    legacy_add += legacy_sum;
  }

  const uint8_t actual_add = frame.back();
  if (actual_add == static_cast<uint8_t>(standard_add & 0xFFU)) {
    return BcpChecksumResult::STANDARD;
  }
  if (actual_add == static_cast<uint8_t>(legacy_add & 0xFFU)) {
    return BcpChecksumResult::LEGACY;
  }
  return BcpChecksumResult::INVALID_ADD;
}

CBoardOdomSample applyOdomAxisInversion(
  const CBoardOdomSample & sample, bool invert_x, bool invert_y, bool invert_yaw)
{
  CBoardOdomSample output = sample;
  const double x_sign = invert_x ? -1.0 : 1.0;
  const double y_sign = invert_y ? -1.0 : 1.0;
  const double yaw_sign = invert_yaw ? -1.0 : 1.0;
  output.x *= x_sign;
  output.vx *= x_sign;
  output.y *= y_sign;
  output.vy *= y_sign;
  output.yaw *= yaw_sign;
  output.wz *= yaw_sign;
  return output;
}

const char * odomRejectReasonName(OdomRejectReason reason)
{
  switch (reason) {
    case OdomRejectReason::NONE:
      return "none";
    case OdomRejectReason::NON_FINITE:
      return "non_finite";
    case OdomRejectReason::POSITION_RANGE:
      return "position_range";
    case OdomRejectReason::LINEAR_SPEED_RANGE:
      return "linear_speed_range";
    case OdomRejectReason::ANGULAR_SPEED_RANGE:
      return "angular_speed_range";
    case OdomRejectReason::POSITION_JUMP:
      return "position_jump";
    case OdomRejectReason::YAW_JUMP:
      return "yaw_jump";
  }
  return "unknown";
}

OdomGuard::OdomGuard(const OdomGuardConfig & config)
: config_(config)
{
}

void OdomGuard::setConfig(const OdomGuardConfig & config)
{
  config_ = config;
  reset();
}

void OdomGuard::reset()
{
  initialized_ = false;
  last_raw_ = CBoardOdomSample{};
  last_output_ = CBoardOdomSample{};
  last_receive_time_ms_ = 0;
  epoch_yaw_offset_ = 0.0;
  epoch_translation_x_ = 0.0;
  epoch_translation_y_ = 0.0;
  reset_candidate_count_ = 0U;
  reset_candidate_last_ = CBoardOdomSample{};
  reset_candidate_time_ms_ = 0;
}

double OdomGuard::normalizeAngle(double angle)
{
  while (angle > PI) {
    angle -= 2.0 * PI;
  }
  while (angle < -PI) {
    angle += 2.0 * PI;
  }
  return angle;
}

bool OdomGuard::sampleWithinAbsoluteLimits(
  const CBoardOdomSample & sample, OdomRejectReason & reason) const
{
  if (!std::isfinite(sample.vx) || !std::isfinite(sample.vy) || !std::isfinite(sample.wz) ||
    !std::isfinite(sample.x) || !std::isfinite(sample.y) || !std::isfinite(sample.yaw))
  {
    reason = OdomRejectReason::NON_FINITE;
    return false;
  }
  if (std::abs(sample.x) > config_.max_abs_position_m ||
    std::abs(sample.y) > config_.max_abs_position_m)
  {
    reason = OdomRejectReason::POSITION_RANGE;
    return false;
  }
  if (std::hypot(sample.vx, sample.vy) > config_.max_linear_speed_mps) {
    reason = OdomRejectReason::LINEAR_SPEED_RANGE;
    return false;
  }
  if (std::abs(sample.wz) > config_.max_angular_speed_radps) {
    reason = OdomRejectReason::ANGULAR_SPEED_RANGE;
    return false;
  }
  return true;
}

bool OdomGuard::deltaIsPlausible(
  const CBoardOdomSample & from, const CBoardOdomSample & to, int64_t dt_ms,
  OdomRejectReason & reason) const
{
  const double dt = std::max(0.001, std::min(0.2, static_cast<double>(dt_ms) / 1000.0));
  const double max_position_delta = config_.max_linear_speed_mps * dt +
    config_.position_jump_margin_m;
  if (std::hypot(to.x - from.x, to.y - from.y) > max_position_delta) {
    reason = OdomRejectReason::POSITION_JUMP;
    return false;
  }

  const double max_yaw_delta = config_.max_angular_speed_radps * dt +
    config_.yaw_jump_margin_rad;
  if (std::abs(normalizeAngle(to.yaw - from.yaw)) > max_yaw_delta) {
    reason = OdomRejectReason::YAW_JUMP;
    return false;
  }
  return true;
}

bool OdomGuard::updateResetCandidate(const CBoardOdomSample & raw, int64_t receive_time_ms)
{
  if (std::hypot(raw.x, raw.y) > config_.reset_origin_radius_m) {
    reset_candidate_count_ = 0U;
    return false;
  }

  if (reset_candidate_count_ == 0U) {
    reset_candidate_count_ = 1U;
  } else {
    OdomRejectReason reason = OdomRejectReason::NONE;
    if (deltaIsPlausible(
        reset_candidate_last_, raw, receive_time_ms - reset_candidate_time_ms_, reason))
    {
      ++reset_candidate_count_;
    } else {
      reset_candidate_count_ = 1U;
    }
  }

  reset_candidate_last_ = raw;
  reset_candidate_time_ms_ = receive_time_ms;
  return reset_candidate_count_ >= std::max(1U, config_.reset_confirm_frames);
}

CBoardOdomSample OdomGuard::transformSample(const CBoardOdomSample & raw) const
{
  const double cos_offset = std::cos(epoch_yaw_offset_);
  const double sin_offset = std::sin(epoch_yaw_offset_);

  CBoardOdomSample output = raw;
  output.x = epoch_translation_x_ + cos_offset * raw.x - sin_offset * raw.y;
  output.y = epoch_translation_y_ + sin_offset * raw.x + cos_offset * raw.y;
  output.yaw = normalizeAngle(raw.yaw + epoch_yaw_offset_);
  return output;
}

void OdomGuard::acceptSample(const CBoardOdomSample & raw, int64_t receive_time_ms)
{
  last_raw_ = raw;
  last_output_ = transformSample(raw);
  last_receive_time_ms_ = receive_time_ms;
  reset_candidate_count_ = 0U;
}

void OdomGuard::beginNewEpoch(const CBoardOdomSample & raw, int64_t receive_time_ms)
{
  epoch_yaw_offset_ = normalizeAngle(last_output_.yaw - raw.yaw);
  const double cos_offset = std::cos(epoch_yaw_offset_);
  const double sin_offset = std::sin(epoch_yaw_offset_);
  epoch_translation_x_ = last_output_.x - (cos_offset * raw.x - sin_offset * raw.y);
  epoch_translation_y_ = last_output_.y - (sin_offset * raw.x + cos_offset * raw.y);
  acceptSample(raw, receive_time_ms);
}

OdomGuardResult OdomGuard::process(const CBoardOdomSample & raw, int64_t receive_time_ms)
{
  OdomGuardResult result;
  result.sample = raw;

  if (!sampleWithinAbsoluteLimits(raw, result.reason)) {
    return result;
  }

  if (!initialized_) {
    initialized_ = true;
    acceptSample(raw, receive_time_ms);
    result.accepted = true;
    result.sample = last_output_;
    return result;
  }

  const int64_t gap_ms = std::max<int64_t>(0, receive_time_ms - last_receive_time_ms_);
  OdomRejectReason delta_reason = OdomRejectReason::NONE;
  if (deltaIsPlausible(last_raw_, raw, gap_ms, delta_reason)) {
    acceptSample(raw, receive_time_ms);
    result.accepted = true;
    result.sample = last_output_;
    return result;
  }

  const bool reset_after_gap = gap_ms >= config_.reset_gap_ms &&
    std::hypot(raw.x, raw.y) <= config_.reset_origin_radius_m;
  if (reset_after_gap || updateResetCandidate(raw, receive_time_ms)) {
    beginNewEpoch(raw, receive_time_ms);
    result.accepted = true;
    result.reset_compensated = true;
    result.sample = last_output_;
    return result;
  }

  result.reason = delta_reason;
  return result;
}

}  // namespace standard_robot_pp_ros2
